# CS 352 project part 2
# this is the initial socket library for project 2 
# You wil need to fill in the various methods in this
# library 

# main libraries 
import binascii
import socket as syssock
import struct
import sys
import threading
import struct
import sys
import time
from random import randint

# encryption libraries 
import nacl.utils
import nacl.secret
import nacl.utils
from nacl.public import PrivateKey, Box

# if you want to debug and print the current stack frame 
from inspect import currentframe, getframeinfo

# these are globals to the sock352 class and
# define the UDP ports all messages are sent
# and received from

# the ports to use for the sock352 messages 
global sock352portTx
global sock352portRx
# the public and private keychains in hex format 
global publicKeysHex
global privateKeysHex

# the public and private keychains in binary format 
global publicKeys
global privateKeys

# the encryption flag 
global ENCRYPT

publicKeysHex = {}
privateKeysHex = {}
publicKeys = {}
privateKeys = {}

# this is 0xEC 
ENCRYPT = 236

# this is the structure of the sock352 packet 
PACKET_HEADER_FORMAT = "!BBBBHHLLQQLL"
PACKET_HEADER_LENGTH = struct.calcsize(PACKET_HEADER_FORMAT)

# Global variables that are responsible for storing the maximum packet size and the
# maximum payload size
MAXIMUM_PACKET_SIZE = 4096
MAXIMUM_PAYLOAD_SIZE = MAXIMUM_PACKET_SIZE - PACKET_HEADER_LENGTH
MAX_WINDOW = 32000
CONGESTION_WINDOW = 2

# Global variables that define all the packet bits
SOCK352_SYN = 0x01
SOCK352_FIN = 0x02
SOCK352_ACK = 0x04
SOCK352_RESET = 0x08
SOCK352_HAS_OPT = 0x10

# Global variables that store the index for the flag, sequence no. and ack no. within the packet header
PACKET_FLAG_INDEX = 1
PACKET_SEQUENCE_NO_INDEX = 8
PACKET_ACK_NO_INDEX = 9
window_index = 10

# String message to print out that a connection has been already established
CONNECTION_ALREADY_ESTABLISHED_MESSAGE = "This socket supports a maximum of one connection\n" \
                                         "And a connection is already established"


def init(UDPportTx, UDPportRx):
    global sock352portTx
    global sock352portRx

    # create the sockets to send and receive UDP packets on 
    # if the ports are not equal, create two sockets, one for Tx and one for Rx

    # Sets the transmit port to 27182 (default) if its None or 0
    if (UDPportTx is None or UDPportTx == 0):
        UDPportTx = 27182

    # Sets the receive port to 27182 (default) if its None or 0
    if (UDPportRx is None or UDPportRx == 0):
        UDPportRx = 27182

    # Assigns the global transmit and receive ports to be the one passed in through this method
    sock352portTx = int(UDPportTx)
    sock352portRx = int(UDPportRx)


# read the keyfile. The result should be a private key and a keychain of
# public keys
def readKeyChain(filename):
    global publicKeysHex
    global privateKeysHex
    global publicKeys
    global privateKeys

    if (filename):
        try:
            keyfile_fd = open(filename, "r")
            for line in keyfile_fd:
                words = line.split()
                # check if a comment
                # more than 2 words, and the first word does not have a
                # hash, we may have a valid host/key pair in the keychain
                if ((len(words) >= 4) and (words[0].find("#") == -1)):
                    host = words[1]
                    #print("host: " + str(host))
                    port = words[2]
                    #print("port: " + str(port))

                    keyInHex = words[3]
                    #print("key: " + keyInHex)

                    if (words[0] == "private"):
                        privateKeysHex[(host, port)] = keyInHex
                        # print("key is private: " + str(keyInHex))
                        privateKeys[(host, port)] = nacl.public.PrivateKey(keyInHex, nacl.encoding.HexEncoder)
                    elif (words[0] == "public"):
                        publicKeysHex[(host, port)] = keyInHex
                        # print("key is public: " + str(keyInHex))
                        publicKeys[(host, port)] = nacl.public.PublicKey(keyInHex, nacl.encoding.HexEncoder)

        except Exception as e:
            print("error: opening keychain file: %s %s" % (filename, repr(e)))
    else:
        print("error: No filename presented")

    #print(publicKeysHex)
    #print(privateKeysHex)

    return (publicKeys, privateKeys)


class socket:

    def __init__(self):

        # creates the socket
        self.socket = syssock.socket(syssock.AF_INET, syssock.SOCK_DGRAM)

        # sets the timeout to be 0.2 seconds
        self.socket.settimeout(0.2)

        # sets the send address to be None (to be initialized later)
        self.send_address = None

        # sets the boolean for whether or not the socket is connected
        self.is_connected = False

        # controls whether or not this socket can close (it's only allowed to close once all data is received)
        self.can_close = False

        # selects a random sequence number between 1 and 100000 as the first sequence number
        self.sequence_no = randint(1, 100000)

        # sets the ack number of the socket to be 0, inititalized later when connection is established
        self.ack_no = 0

        # declares the data packets array, for the sender its the packets it sends and for the receiver, its the
        # packets it has received
        self.data_packets = []

        # declares the file length, which will set later (in send by the client and in recv by the server)
        self.file_len = -1

        # declares the retransmit boolean which represents whether or not to resend packets and Go-Back-N
        self.retransmit = False

        # the corresponding lock for the retransmit boolean
        self.retransmit_lock = threading.Lock()

        # declares the last packet that was acked (for the sender only)
        self.last_data_packet_acked = None

        #create an encrypt checking flag. equals true when encrypt passed as argument
        self.encrypt = False

        #create a Box field, later to be initialized within connnect and accept
        self.encrypt_box = None
        
        # receiving window sent by reciever to sender; helps sender keep track of how much to send
        self.recvwindow = MAX_WINDOW

        #number of packets sent by sender in its congestion / flow control window
        self.pack_sent=0

        #number of ACKS received by sender from previous window
        self.ack_recv=0

        #a counter to know how much the congestion window should be after RTTS
        self.iterate=2

        #once all ACKS from the previous window are received, we can proceed to send the next set of packets in the next window
        self.can_send = True
        
        #lock to allow only one thread at a time to udpate self.ack_rec
        self.ack_lock = threading.Lock()
        
        #lock to allow only one thread at a time to update self.can_send
        self.send_lock = threading.Lock()
      
        self.buffer_size=MAX_WINDOW

        self.buffer=""


        return

    def bind(self, address):
        # bind is not used in this assignment
        self.socket.bind((address[0], sock352portRx))
        return

    def connect(self, *args):

        # example code to parse an argument list (use option arguments if you want)
        global sock352portTx
        global ENCRYPT
        if (len(args) >= 1):
            (host, port) = args[0]
        if (len(args) >= 2):
            if (args[1] == ENCRYPT):
                self.encrypt = True
                print("connection is encrypted")

        # your code goes here

        address = args[0]

        # sets the send address to the tuple (address ip, transmit port)
        self.send_address = (address[0], sock352portTx)
        print("send address is: ", self.send_address)

        # binds the client on the receiving port
        self.socket.bind((address[0], sock352portRx))

        # makes sure the client isn't already connected. If it is, prints an error message
        if self.is_connected:
            print(CONNECTION_ALREADY_ESTABLISHED_MESSAGE)
            return

        # Step 1: Request to connect to the server by setting the SYN flag

        # if encryption argument passed, set the option bit and syn flag
        if (self.encrypt == True):
            flags = SOCK352_SYN | SOCK352_HAS_OPT
        else:
            flags = SOCK352_SYN

        # first the packet is created using createPacket and passing in the apprpriate variables
        syn_packet = self.createPacket(flags, sequence_no=self.sequence_no)
        self.socket.sendto(syn_packet, self.send_address)
        # increments the sequence since it was consumed in creation of the SYN packet
        self.sequence_no += 1

        # Receives the SYN_ACK from Step 2 within accept()

        received_handshake_packet = False
        while not received_handshake_packet:
            try:
                # tries to receive a SYN/ACK packet from the server using recvfrom and unpacks it
                (syn_ack_packet, addr) = self.socket.recvfrom(PACKET_HEADER_LENGTH)
                syn_ack_packet = struct.unpack(PACKET_HEADER_FORMAT, syn_ack_packet)
                # if it receives a reset marked flag for any reason, abort the handshake
                if syn_ack_packet[PACKET_FLAG_INDEX] == SOCK352_RESET:
                    print("Connection was reset by the server")
                    return

                # if it receives a packet, and it is SYN/ACK, we are done
                if syn_ack_packet[PACKET_FLAG_INDEX] == SOCK352_SYN | SOCK352_ACK:
                    received_handshake_packet = True

                # if it receives a packet with an incorrect ACK from its sequence number,
                # it tries to receive more packets
                if syn_ack_packet[PACKET_ACK_NO_INDEX] != self.sequence_no:
                    received_handshake_packet = False
            # retransmits the SYN packet in case of timeout when receiving a SYN/ACK from the server
            except syssock.timeout:
                self.socket.sendto(syn_packet, self.send_address)

        # sets the client's acknowledgement number to be SYN/ACK packet's sequence number + 1
        self.ack_no = syn_ack_packet[PACKET_SEQUENCE_NO_INDEX] + 1

        # Step 3: Send a packet with the ACK flag set to acknowledge the SYN/ACK packet
        ack_packet = self.createPacket(flags=SOCK352_ACK,
                                       sequence_no=self.sequence_no,
                                       ack_no=self.ack_no)
        # increments the sequence number as it was consumed by the ACK packet
        self.sequence_no += 1

        # sets the connected boolean to be true
        self.is_connected = True

        # after the client is connected, look up private key of client and public key of server

        if(self.encrypt==True):

            #get host and port for public key look up from address passed into argument
            serverhost = str(self.send_address[0])
            serverport = str(self.send_address[1])

            #if the host is not found, use "*", port
            #if the port is not found, use host,"*"
            #if host and port are not found, use "*","*"
            #else,key not found, exit program

            if( (publicKeys.get( (serverhost, serverport)) !=None)):
                serverpublickey = publicKeys.get((serverhost, serverport))

            elif( (publicKeys.get( ("*", serverport) ) !=None)):
                serverpublickey  = publicKeys.get( ("*", serverport) )

            elif ((publicKeys.get((serverhost, "*")) != None)):
                serverpublickey = publicKeys.get( (serverhost, "*"))

            elif ((publicKeys.get(("*", "*")) != None)):
                serverpublickey = publicKeys.get(("*", "*"))

            else:
                print("server public key not found")
                exit(1)

            #print(serverpublickey)

            #get port for the private key. use destination for the host
            clienthost = str(self.send_address[0])
            clientport = str(sock352portTx)

            # if the host is not found, use "*", port
            # if the port is not found, use host,"*"
            # if host and port are not found, use "*","*"
            # also check for localhost as host
            #else key not found, exit program
            if ((privateKeys.get((clienthost, clientport)) != None)):
                clientprivatekey = privateKeys.get((clienthost, clientport))

            elif ((privateKeys.get(("*", clientport)) != None)):
                clientprivatekey = privateKeys.get(("*", clientport))

            elif ((privateKeys.get((clienthost, "*")) != None)):
                clientprivatekey = privateKeys.get((clienthost, "*"))

            elif ((privateKeys.get(("localhist", clientport)) != None)):
                clientprivatekey = privateKeys.get(("localhost", clientport))

            elif ((privateKeys.get(("localhost", "*")) != None)):
                clientprivatekey = privateKeys.get(("localhost", "*"))

            elif ((privateKeys.get(("*", "*")) != None)):
                clientprivatekey = privateKeys.get(("*", "*"))

            else:
                print("client private key not found")
                exit(1)

            #print(clientprivatekey)


            #create a box to encrypt the message using client's private key and server's public key
            self.encrypt_box = Box(clientprivatekey, serverpublickey)

        # sends the ack packet to the server, as it assumes it's connected now
        self.socket.sendto(ack_packet, self.send_address)
        print("Client is now connected to the server at %s:%s" % (self.send_address[0], self.send_address[1]))

    def listen(self, backlog):
        # listen is not used in this assignments
        pass

    def accept(self, *args):
        # example code to parse an argument list (use option arguments if you want)
        global ENCRYPT
        if (len(args) >= 1):
            if (args[0] == ENCRYPT):
                self.encrypt = True
        # your code goes here
        # makes sure again that the server is not already connected
        # because part 1 supports a single connection only
        if self.is_connected:
            print(CONNECTION_ALREADY_ESTABLISHED_MESSAGE)
            return

        #print("host name is: ", self.socket.getsockname())

        # Keeps trying to receive the request to connect from a potential client until we get a connection request
        got_connection_request = False
        while not got_connection_request:
            try:
                # tries to receive a potential SYN packet and unpacks it
                (syn_packet, addr) = self.socket.recvfrom(PACKET_HEADER_LENGTH)
                syn_packet = struct.unpack(PACKET_HEADER_FORMAT, syn_packet)

                # if the received packet is not a SYN packet, it ignores the packet
                # treat the connection as encrypted only when both the argument is passed as ENCRYPT
                # and option bit is in the packet, otherwise connection is not encrypted
                if (syn_packet[PACKET_FLAG_INDEX] == SOCK352_SYN):
                    got_connection_request = True
                    self.encrypt = False

                if (syn_packet[PACKET_FLAG_INDEX] == SOCK352_SYN | SOCK352_HAS_OPT):
                    got_connection_request = True


            # if the receive times out while receiving a SYN packet, it tries to listen again
            except syssock.timeout:
                pass

        # Step 2: Send a SYN/ACK packet for the 3-way handshake
        # creates the flags bit to be the bit-wise OR of SYN/ACK
        flags = SOCK352_SYN | SOCK352_ACK
        #print("ack and syn flag:", bin(flags))
        # creates the SYN/ACK packet to ACK the connection request from client
        # and sends the SYN to establish the connection from this end
        syn_ack_packet = self.createPacket(flags=flags,
                                           sequence_no=self.sequence_no,
                                           ack_no=syn_packet[PACKET_SEQUENCE_NO_INDEX] + 1)
        # increments the sequence number as it just consumed it when creating the SYN/ACK packet
        self.sequence_no += 1
        # sends the created packet to the address from which it received the SYN packet
        self.socket.sendto(syn_ack_packet, addr)

        # Receive the final ACK to complete the handshake and establish connection
        got_final_ack = False
        while not got_final_ack:
            try:
                # keeps trying to receive the final ACK packet to finalize the connection
                (ack_packet, addr) = self.socket.recvfrom(PACKET_HEADER_LENGTH)
                ack_packet = struct.unpack(PACKET_HEADER_FORMAT, ack_packet)
                # if the unpacked packet has the ACK flag set, we are done
                if ack_packet[PACKET_FLAG_INDEX] == SOCK352_ACK:
                    got_final_ack = True
            # if the server times out when trying to receive the final ACK, it retransmits the SYN/ACK packet
            except syssock.timeout:
                self.socket.sendto(syn_ack_packet, addr)

        # updates the server's ack number to be the last packet's sequence number + 1
        self.ack_no = ack_packet[PACKET_SEQUENCE_NO_INDEX] + 1

        # updates the server's send address
        self.send_address = (addr[0], sock352portTx)

        # connect to the client using the send address just set
        # self.socket.connect(self.send_address)

        # updates the connected boolean to reflect that the server is now connected
        self.is_connected = True

        print("Server is now connected to the client at %s:%s" % (self.send_address[0], self.send_address[1]))

        if (self.encrypt == True):

            # get port for the private key, which is UDPTx
            serverhost = str(addr[0])
            serverport = str(sock352portTx)

            # if the host is not found, use "*", port
            # if the port is not found, use host,"*"
            # if host and port are not found, use "*","*"
            # also check for localhost
            # else,key not found, exit program

            if ((privateKeys.get((serverhost, serverport)) != None)):
                serverprivatekey = privateKeys.get((serverhost, serverport))

            elif ((privateKeys.get(("localhost", serverport)) != None)):
                serverprivatekey = privateKeys.get(("localhost", serverport))

            elif ((privateKeys.get(("localhost", "*")) != None)):
                serverprivatekey = privateKeys.get(("localhost", "*"))

            elif ((privateKeys.get(("*", serverport)) != None)):
                serverprivatekey = privateKeys.get(("*", serverport))

            elif ((privateKeys.get((serverhost, "*")) != None)):
                serverprivatekey = privateKeys.get((serverhost, "*"))

            elif ((privateKeys.get(("*", "*")) != None)):
                serverprivatekey = privateKeys.get(("*", "*"))

            else:
                print("server private key not found")
                exit(1)

            #print("server private key is: ", str(serverprivatekey))

            # get host and port for public key look up from address passed into argument
            clienthost = str(addr[0])
            clientport = str(sock352portTx)

            # if host is not found, first try at localhost because localhost address is sometimes
            # converted to a numeric addresss
            # if the host is not found, use "*", port
            # if the port is not found, use host,"*"
            # if host and port are not found, use "*","*"
            # else key not found, exit program
            if ((publicKeys.get((clienthost, clientport)) != None)):
                clientpublickey = publicKeys.get((clienthost, clientport))

            elif ((publicKeys.get(("localhost", clientport)) != None)):
                clientpublickey = publicKeys.get(("localhost", clientport))

            elif ((publicKeys.get(("localhost", "*")) != None)):
                clientpublickey = publicKeys.get(("localhost", clientport))

            elif ((publicKeys.get(("*", clientport)) != None)):
                clientpublickey = publicKeys.get(("*", clientport))

            elif ((publicKeys.get((clienthost, "*")) != None)):
                clientpublickey = publicKeys.get((clienthost, "*"))

            elif ((publicKeys.get(("*", "*")) != None)):
                clientpublickey = publicKeys.get(("*", "*"))

            else:
                print("client public key not found")
                exit(1)

            #print("client public key is: " , str(clientpublickey))
            # print(serverpublickey)
            # print(clientprivatekey)

            #create a box to decrypt later
            self.encrypt_box = Box(serverprivatekey, clientpublickey)

        return self, addr

    def close(self):
        # makes sure there is a connection established in the first place before trying to close it
        if not self.is_connected:
            print("No connection is currently established that can be closed")
            return

        # checks if the server can close the connection (it can close only when it has received the last packet/ack)
        if self.can_close:
            # calls the socket's close method to finally close the connection
            self.socket.close()
            # resets all the appropriate variables
            self.send_address = None
            self.is_connected = False
            self.can_close = False
            self.sequence_no = randint(1, 100000)
            self.ack_no = 0
            self.data_packets = []
            self.file_len = -1
            self.retransmit = False
            self.last_data_packet_acked = None
        # in the case that it cannot close, it prints out that it's still waiting for data
        else:
            print
            "Failed to close the connection!\n" \
            "Still waiting for data transmission/reception to finish"

            # method responsible for breaking apart the buffer into chunks of maximum payload length

    def create_data_packets(self, buffer):

        # calculates the total packets needed to transmit the entire buffer
        total_packets = (int)(len(buffer) / MAXIMUM_PAYLOAD_SIZE)

        # if the length of the buffer is not divisible by the maximum payload size,
        # that means an extra packet will need to be sent to transmit the left over data
        # so it increments total packets by 1
        if len(buffer) % MAXIMUM_PAYLOAD_SIZE != 0:
            total_packets += 1

        # sets the payload length to be the maximum payload size
        payload_len = MAXIMUM_PAYLOAD_SIZE

        # iterates up to total packets and creates each packet
        for i in range(0, total_packets):
            # if we are about to construct the last packet, checks if the payload length
            # needs to adjust to reflect the left over size or the entire maximum packet size
            if i == total_packets - 1:
                if len(buffer) % MAXIMUM_PAYLOAD_SIZE != 0:
                    payload_len = len(buffer) % MAXIMUM_PAYLOAD_SIZE

            # creates the new packet with the appropriate header
            new_packet = self.createPacket(flags=0x0,
                                           sequence_no=self.sequence_no,
                                           ack_no=self.ack_no,
                                           payload_len=payload_len)
            # consume the sequence and ack no as it was used to create the packet
            self.sequence_no += 1
            self.ack_no += 1

            # attaches the payload length of buffer to the end of the header to finish constructing the packet
            message = buffer[MAXIMUM_PAYLOAD_SIZE * i: MAXIMUM_PAYLOAD_SIZE * i + payload_len]

            # encrypt each packet if encryption is true
            if (self.encrypt):
                #print("message is :", message)
                #print(type(self.encrypt_box))
                encrypt_packet = self.encrypt_box.encrypt(message)
                self.data_packets.append(new_packet + encrypt_packet)
            else:
                self.data_packets.append(new_packet + message)

        return total_packets

     def send(self, buffer):
        # makes sure that the file length is set and has been communicated to the receiver
        if self.file_len == -1:
            self.socket.sendto(buffer, self.send_address)
            self.file_len = struct.unpack("!L", buffer)[0]
            print("File length sent: " + str(self.file_len) + " bytes")
            return self.file_len

        # sets the starting sequence number and creates data packets starting from this number
        start_sequence_no = self.sequence_no
        total_packets = self.create_data_packets(buffer)

        # creates another thread that is responsible for receiving acks for the data packets sent
        recv_ack_thread = threading.Thread(target=self.recv_acks, args=())
        recv_ack_thread.setDaemon(True)
        recv_ack_thread.start()

        # starts the data packet transmission
        print("Started data packet transmission...")
        print("total packets: " + str(total_packets))
        while not self.can_close:
            # calculates the index from which to start sending packets
            # when sending the first time, it will be 0
            # otherwise, when retransmitting, it will calculate the Go-Back-N based
            # on the last data packet that was acked
            if self.last_data_packet_acked is None:
                resend_start_index = 0
            else:
                resend_start_index = int(self.last_data_packet_acked[PACKET_ACK_NO_INDEX]) - start_sequence_no

            #print("index:" + str(resend_start_index))
            # checks if the packet to start retransmitting from is the total amount of packets this
            # would mean the last data packet has been transmitted and so its safe to close the connection
            if resend_start_index == total_packets:
                self.can_close = True


            # adjusts retransmit to indicate that the sender started retransmitting using locks
            self.retransmit_lock.acquire()
            self.retransmit = False
            self.retransmit_lock.release()

            # continually tries to transmit packets while the connection cannot be closed from resend start index
            # to the rest of the packets (or at least until as much as it can)
            while not self.can_close and resend_start_index < total_packets and not self.retransmit:
                #print(resend_start_index)
                #print(total_packets)
                # tries to send the packet and catches any connection refused exception which might mean
                # the connection was unexpectedly closed/broken
                #print("total packets: " + str(total_packets))

                try:
                    # if received all the acks for the previous congestion window
                    # then send packets for next incremented congestion window
                    if self.can_send == True:
                        # try to send packets in congestion window, but check if the receiving window is smaller before sending
                        # set the counter of how many packets we sent in this window to 0
                        
                        #reset the number of ack received
                        self.ack_lock.acquire()
                        self.ack_recv=0
                        self.ack_lock.release()
                        #resent the number of packets sent in this window
                        self.pack_sent=0

                        #determine # ofpackets to send
                        # count is the number of packets to send
                        count=0
                        # iter_bytes is the total number of byters we are sending in this window
                        # iter_bytes is used make sure we dont send packets sizes that exceed the window size
                        iter_bytes=0
                        # loop to see if the congestion control window, or the flow control window is the minimum
                        for i in range(self.iterate):
                            # if there are packets left to send AND if there is room for more in flow control window
                            if(resend_start_index+i<total_packets and iter_bytes<self.recvwindow):
                                # if the packet to send is larger than the flow control window, then split the packet by how much the window wants
                                if(iter_bytes + len(self.data_packets[resend_start_index+i]) > self.recvwindow):
                                    self.split(resend_start_index+i, self.recvwindow - iter_bytes)
                                    #increment total packets because splitting the packet adds an extra packet
                                    total_packets+=1
                                #add the packet that we can send into the total number of bytes we are sending in this window
                                iter_bytes+=len(self.data_packets[resend_start_index+i])
                                #we can send this packet later
                                count+=1
                        print("packs to send:" + str(count))
                        #send the packets that fit in the congestion control or flow control window, increment the packets sent and its index
                        for i in range(count):
                            self.socket.sendto(self.data_packets[resend_start_index], self.send_address)
                            self.pack_sent+=1
                            print("pack size:" +  str(len(self.data_packets[resend_start_index])))
                            resend_start_index+=1
                        #wait for all ACKS for the packets just sent to be received before sending packets in next window
                        #all packets have been sent so now we should not send anymore until these packets receive their ACKS
                        self.send_lock.acquire()
                        self.can_send=False
                        self.send_lock.release()
                # Catch error 111 (Connection refused) in the case where the last ack
                # was received by this sender and thus the connection was closed
                # by the receiver but it happened between this sender's checking
                # of that connection close condition
                except syssock.error as error:
                    if error.errno != 111:
                        raise error
                    self.can_close = True
                    break
        # waits for recv thread to finish before returning from the method
        recv_ack_thread.join()

        #send a packet to the receiver to let them know there are no more bytes to be sent
        fin_packet = self.createPacket(flags=SOCK352_FIN,
                                               sequence_no=self.sequence_no+1,
                                               ack_no=self.ack_no+1,
                                               window=MAX_WINDOW)
        self.socket.sendto(fin_packet, self.send_address)
        print("Finished transmitting data packets")
        return len(buffer)


    # this method take a packet that is too large to fit in the flow control window, and splits it into two.
    # it splits it into how much more room the window has, and whatever is left
    # it takes the index of the packet to be split and the remaining window size
    def split(self,index, val):
      # unpack header, retrieve ACKS and SEQS
        packet= self.data_packets[index]
        packet_header = packet[:PACKET_HEADER_LENGTH]
        packet_data = packet[PACKET_HEADER_LENGTH:]
        packet_header = struct.unpack(PACKET_HEADER_FORMAT, packet_header)
        seq_no=packet_header[PACKET_SEQUENCE_NO_INDEX]
        ack_no=packet_header[PACKET_ACK_NO_INDEX]
        #slice the packet_data
        #The total length of the packet should be the remaining window size which includes the header and data length
        send1=packet_data[:val-40]
        send2=packet_data[val-40:]
        
        #create the new packets. the 2nd packet should have an ACK and SEQ NO 1 more than the 1st
        packet1 = self.createPacket(flags=0x0,
                                           sequence_no=seq_no,
                                           ack_no=ack_no,
                                           payload_len=len(send1))
        packet2=self.createPacket(flags=0x0,
                                           sequence_no=seq_no+1,
                                           ack_no=ack_no+1,
                                           payload_len=len(send2))

        # insert the proper data packets in the right spot and remove the previous data packet that was too big
        self.data_packets.insert(index,packet2+send2)
        self.data_packets.insert(index,packet1+send1)
        self.data_packets.pop(index+2)

        # update the rest of the data packets remaining and increase their ACK and SEQ NOs by 1
        for i in range(index+2,len(self.data_packets)):
            pack= self.data_packets[i]
            pack_header = pack[:PACKET_HEADER_LENGTH]
            pack_data = pack[PACKET_HEADER_LENGTH:]
            pack_header = struct.unpack(PACKET_HEADER_FORMAT, pack_header)
            seq=pack_header[PACKET_SEQUENCE_NO_INDEX]
            ack=pack_header[PACKET_ACK_NO_INDEX]
            packet=self.createPacket(flags=0x0,
                                           sequence_no=seq+1,
                                           ack_no=ack+1,
                                           payload_len=len(pack_data))
            self.data_packets[i]=packet+pack_data

      
    # method responsible for receiving acks for the data packets the sender sends
    def recv_acks(self):
        # tries to receive the ack as long as the connection is not ready to be closed
        # this can only happen when the sender receives a Connection refused error
        while not self.can_close:
            # tries to receive the new packet and un-pack it
            try:
                new_packet = self.socket.recv(PACKET_HEADER_LENGTH)
                new_packet = struct.unpack(PACKET_HEADER_FORMAT, new_packet)
                #receving window set by the reciever when ack is sent back to sender
                self.recvwindow = new_packet[window_index]
                #print("in client, recv window is : "  + str(self.recvwindow))
            
                # if the window received is 0, then wait and do not send
                if(self.recvwindow == 0):
                    self.send_lock.acquire()
                    self.can_send = False
                    self.send_lock.release()
                    
                # if the window recieved is not 320000, then increment the ACK received
                # this is because if the ACK received is 32000, then the ACK was just sent to update the buffer, not because a packet was actually sent
                if(self.recvwindow !=32000):
                    self.ack_lock.acquire()
                    self.ack_recv+=1
                    self.ack_lock.release()
                    
                # if we received all the packets sent and there is enough window size , then multiply congestion window by 2. Now we can send the next set of packets
                if(self.ack_recv == self.pack_sent and self.can_send == False and self.recvwindow>0):
                    #print(self.ack_recv, self.pack_sent)
                    self.iterate*=2
                    self.send_lock.acquire()
                    self.can_send = True
                    self.send_lock.release()
                    print("recv window after all ACKS: " + str(self.recvwindow))
                # ignores the packet if the ACK flag is not set.
                if new_packet[PACKET_FLAG_INDEX] != SOCK352_ACK:
                    continue

                # if the last data packet acked is not set, the newly received packet is set to be the last data packet
                # acked. Otherwise, checks if the new packet's sequence number is greater than the last data packet
                # acked's sequence number, otherwise it assumes it could be a duplicate ACK
                if (self.last_data_packet_acked is None or \
                        new_packet[PACKET_SEQUENCE_NO_INDEX] > self.last_data_packet_acked[
                    PACKET_SEQUENCE_NO_INDEX]):
                        self.last_data_packet_acked = new_packet


            # in the case where the recv times out, it locks down retransmit and sets it to True
            # to indicate that no ACk was received within the timeout window of 0.2 seconds
            except syssock.timeout:
                self.retransmit_lock.acquire()
                self.retransmit = True
                self.retransmit_lock.release()

            # Catch error 111 (Connection refused) in the case where the sender is
            # anticipating an ACK for a packet it sent out, which hasn't timed out
            # but the server has closed the connection since it finished receiving
            # the data and an ACK is already on its way to this sender
            except syssock.error as error:
                if error.errno != 111:
                    raise error
                    self.can_close = True
                    return

    def recv(self, nbytes):
        # if the file length has not been set, receive the file length from the sender
        if self.file_len == -1:
            file_size_packet = self.socket.recv(struct.calcsize("!L"))
            self.file_len = struct.unpack("!L", file_size_packet)[0]
            print("File Length Received: " + str(self.file_len) + " bytes")
            return file_size_packet

        # sets the bytes to receive to be how many bytes it expects
        bytes_to_receive = nbytes
        # also declares a variable to hold all the string of the data that has been received
        data_received = ""

        #keeps track of upto how much of the buffer can be cleared based on nbytes


        #boolean to check that nbytes amount has reached and recv. should return by clearning the buffer of that amount
        full = False

        print(" n bytes to recv : " + str(bytes_to_receive))

        print("Started receiving data packets...")
        # keep trying to receive packets until the receiver has more bytes left to receive
        while bytes_to_receive > 0 and full==False:
            # tries to receive the packet

            if (self.buffer_size <= 0):
                self.buffer_size = MAX_WINDOW
                #send ack to sender letting it know the buffer is is now being reset 
                ack_packet = self.createPacket(flags=SOCK352_ACK,
                                               sequence_no=self.sequence_no-1,
                                               ack_no=self.ack_no,
                                               window=MAX_WINDOW)

                self.socket.sendto(ack_packet, self.send_address)

            try:
                # receives the packet of header + maximum data size bytes (although it will be limited
                # by the sender on the other side)
                if(self.encrypt):
                    #add 40 bytes for the encryption information
                    packet_received = self.socket.recv(PACKET_HEADER_LENGTH + bytes_to_receive + 40)
                else:
                    print("in recv current window: " + str(self.buffer_size))

                    try:
                        packet_received = self.socket.recv(self.buffer_size)
                        print("packet size recv: " + str(len(packet_received)))

                        # change the recv window size. subtract the length of the packet recieved from the window size
                        self.buffer_size = self.buffer_size - len(packet_received)

                        print("in recv after receiving packet, the window: " + str(self.buffer_size))

                        if(bytes_to_receive-len(packet_received) < 0):
                            full = True
                            print("full; n bytes now: " + str(bytes_to_receive))

                        else:
                            bytes_to_receive = bytes_to_receive - len(packet_received)
                            print("n bytes now: " + str(bytes_to_receive))

                    except:
                        print("error in recv")
                        OSError
                        return data_received

                # sends the packet to another method to manage it and gets back the data in return
                str_received = self.manage_recvd_data_packet(packet_received, self.buffer_size)

                # adjusts the numbers accordingly based on return value of manage data packet
                if str_received is not None:
                    # appends the data received to the total buffer of all the data received so far
                    self.buffer += str_received

            # catches timeout, in which case it just tries to another packet
            except syssock.timeout:
                pass

        #returns the requested number of bytes
        data_received = self.buffer[:nbytes]

        # since it's done with receiving all the bytes, it marks the socket as safe to close
        self.can_close = True

        print("Finished receiving the data")
        # returns the data received
        return data_received

        # creates a generic packet to be sent using parameters that are
        # relevant to Part 1. The default values are specified above in case one or more parameters are not used

    def createPacket(self, flags=0x0, sequence_no=0x0, ack_no=0x0, payload_len=0x0, window=0x0):
        return struct.Struct(PACKET_HEADER_FORMAT).pack \
                (
                0x1,  # version
                flags,  # flags
                0x0,  # opt_ptr
                0x0,  # protocol
                PACKET_HEADER_LENGTH,  # header_len
                0x0,  # checksum
                0x0,  # source_port
                0x0,  # dest_port
                sequence_no,  # sequence_no
                ack_no,  # ack_no
                window,  # window
                payload_len  # payload_len
            )

        # Manages a packet received based on the flag

    def manage_recvd_data_packet(self, packet,window):
        packet_header = packet[:PACKET_HEADER_LENGTH]
        packet_data = packet[PACKET_HEADER_LENGTH:]
        packet_header = struct.unpack(PACKET_HEADER_FORMAT, packet_header)
        packet_header_flag = packet_header[PACKET_FLAG_INDEX]

        # Check if the packet that was received has the expected sequence no
        # for the next in-order sequence no (which is the ack number)
        #     Case 1, the sequence number is in-order so send back the acknowledgement
        #     Case 2, the sequence number is out-of-order so drop the packet
        print("sequence number of packet : " + str(packet_header[PACKET_SEQUENCE_NO_INDEX]))
        print("ack number in recv: " + str(self.ack_no))

        if packet_header[PACKET_SEQUENCE_NO_INDEX] != self.ack_no:
            return
        if self.encrypt == True:
            #print(type(self.encrypt_box))
            packet_data = self.encrypt_box.decrypt(packet_data)
            #print("this is packet data: ", packet_data)
        # adds the payload data to the data packet array
        self.data_packets.append(packet_data)
        # increments the acknowledgement by 1 since it is supposed to be the next expected sequence number
        self.ack_no += 1
        # finally, it creates the ACK packet using the server's current sequence and ack numbers
        ack_packet = self.createPacket(flags=SOCK352_ACK,
                                       sequence_no=self.sequence_no,
                                       ack_no=self.ack_no,
                                       window = window)
        # the sequence number is incremented since it was consumed upon packet creation
        self.sequence_no += 1
        # the server sends the packet to ACK the data packet it received
        self.socket.sendto(ack_packet, self.send_address)

        # the data or the payload is then itself is returned from this method
        return packet_data
