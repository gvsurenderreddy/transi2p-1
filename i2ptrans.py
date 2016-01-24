from twisted.internet import protocol, reactor, defer
from twisted.internet.endpoints import clientFromString, connectProtocol
from twisted.names import dns, server, client, error
import socket
import struct
import json
from txi2p.bob.endpoints import BOBI2PClientEndpoint

socket.SO_ORIGINAL_DST = 80

try:
    config = json.load(open('config.json'))
except IOError:
    with open('config.json', 'w') as f:
        config = {
            'addr_map': '10.18.0.0',
            'dns_port': 5354,
            'trans_port': 7679
        }

        json.dump(config, f)
except ValueError:
    print('Invalid JSON configuration. RM and try again?')
    quit()

class AddressMap(object):
    def __init__(self):
        self.base_addr = struct.unpack('>I', socket.inet_aton(config['addr_map']))[0]
        self.addr_index = 0

        self.names = {}
        self.addresses = {}

    def map(self, name):
        if name in self.names:
            return self.names[name]
        else:
            self.addr_index += 1
            addr = socket.inet_ntoa(struct.pack('>I', self.base_addr + self.addr_index))

            self.names[name] = addr
            self.addresses[addr] = name
            return addr

    def get_name(self, addr):
        if addr in self.addresses:
            return self.addresses[addr]
        else:
            return None

class EepNS(object):
    def map_address(self, query):
        name = query.name.name
        addr = address_map.map(name)
        answer = dns.RRHeader(name=name, payload=dns.Record_A(address=addr))
        return [ answer ], [], []

    def query(self, query, timeout=None):
        if query.type == dns.A and query.name.name.split('.')[-1] == 'i2p':
            return defer.succeed(self.map_address(query))
        else:
            return defer.fail(error.DomainError())

class EepConnection(protocol.Protocol):
    def __init__(self, proxy):
        self.proxy = proxy

    def dataReceived(self, data):
        self.proxy.transport.write(data)

    def connectionLost(self, reason):
        # clean up
        print(reason)

class TransPort(protocol.Protocol):
    def connectionMade(self):
        self.pending = b''
        self.i2p = None

        # get the ip address they're trying to connect to and open connection
        addr = self.transport.socket.getsockopt(socket.SOL_IP, socket.SO_ORIGINAL_DST, 16)
        _, self.dst_port, self.dst_addr, _ = struct.unpack('>HH4s8s', addr)
        self.dst_addr = socket.inet_ntoa(self.dst_addr)

        print(self.dst_addr, self.dst_port)
        name = address_map.get_name(self.dst_addr)
        if not name:
            # tear it down
            pass

        endpoint = clientFromString(reactor, 'i2p:' + name)
        connectProtocol(endpoint, EepConnection(self)).addCallback(self.i2p_connected)

    def dataReceived(self, data):
        if self.i2p:
            self.i2p.transport.write(data)
        else:
            self.pending += data

    def connectionLost(self, reason):
        # clean up
        print(reason)

    def i2p_connected(self, i2p):
        self.i2p = i2p

        if self.pending:
            self.i2p.transport.write(self.pending)

address_map = AddressMap()
trans_port = protocol.ServerFactory()
trans_port.protocol = TransPort

ns = server.DNSServerFactory(clients=[EepNS(), client.Resolver(servers=[('127.0.0.1', 5353)])])
reactor.listenUDP(config['dns_port'], dns.DNSDatagramProtocol(controller=ns))
reactor.listenTCP(config['trans_port'], trans_port)
print('listening on {}')
reactor.run()
