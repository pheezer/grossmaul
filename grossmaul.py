import pydle
import logging
import collections
import random
import pickle
import time
from botbrain import BotBrain
from types import FunctionType
from importlib import reload

# Modify these for your own nefarious purposes
CHAN = "#thehoppening"
#CHAN = "#thetestening"
NICK = "BeerRobot"
HOST = "chat.freenode.net"
PORT = 6697
LULL = 900 


STATE = {
'allow_delete': ['|MashTun|', 'mashtun'],
'boredom': 0,
'boredom_limit': 700,
'buffer': collections.deque(maxlen = 1000),
'counters':  {"__startup":True},
'timestamp': {},
}

#logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filename=CHAN[1:]+'log.txt')

class GrossmaulBot(pydle.Client):
    """  """
    botbrain = None

    def sendMessage(self, target, message, processing = True):
        global STATE
        """Customize message sending to allow for keyword parsing"""
        # if we're sending a message we're obviously no longer bored
        STATE['boredom'] = 0
        message = message.lstrip().rstrip()

        # Look for a $ that indicates keywords
        if processing:
            for i in range(3):
                if '$' in message:
                    # split into words
                    words = message.split()
                    for word in words:
                        for i in range(word.count('$') // 2):
                            # If there are two $s, keyword is embedded
                            # eg Abso-$keyword$-lutely!
                            keyword = word.split('$')[1+(i*2)]
                            replacement = self.botbrain.findKeyword(keyword.lower())
                            if (replacement is not None):
                                message = message.replace('$' + keyword + '$', replacement, 1)
                            else:
                                message = message.replace('$' + keyword + '$', keyword, 1)

                        if word[0] is '$':
                            # parse into only alphanumeric characters (+ some others)
                            keyword = ''
                            for char in word:
                                if char.isalnum() or char in "-_": keyword += (char)
                            replacement = self.botbrain.findKeyword(keyword.lower())
                            if (replacement is not None):
                                message = message.replace('$' + keyword, replacement, 1)
        
        # If the message starts with /me it is an action, treat accordingly        
        if message.lower().startswith("/me"):
            self.action(target, message[3:].lstrip())
        else:
            # Look for a \n that indicates a newline
            if '\\n' in message:
                lines = message.split('\\n')
                for line in lines:
                    self.sendMessage(target, line, False)
                return
            else:
                #otherwise simply log and send the message
                STATE['buffer'].appendleft( (NICK, message) )
                logging.info("Sending message to %s: %s" % (target, message))
                self.message(target, message)

    def action(self, target, message):
        # send a CTCP message that will be interpreted as an action
        self.ctcp(target, "ACTION", message)


    def on_connect(self):
        """Callback when client has successfully connected. Client will attempt to connect to db and join CHAN."""
        logging.info("Connected to %s" % HOST)    
        self.botbrain = BotBrain()
        self.join(CHAN)

    def on_join(self, channel, user):
        """Called when any user (including this client) joins the channel."""
        global STATE
        global NICK
        logging.info("%s has joined %s" % (user, channel))
        # Detect if the client is using a backup name and if so change NICK
        # If "__startup" is still in STATE['counters'], we will use user as the new NICK
        if("__startup" in STATE['counters']):
            del STATE['counters']["__startup"]
            
            if (NICK != user):
                NICK = user
                logging.info("Changing internal NICK to %s" % NICK)
        # load saved counters to await users
        self.load_counters()

    def on_ctcp(self, by, target, what, contents):
        """Callback when client receives ctcp data"""
        logging.info("CTCP: by: %s - target: %s - what: %s - contents: %s" % (by, target, what, contents))
        

    def on_unknown(self, message):
        """Callback when client receives unknown data"""
        logging.warning("Client received unknown data: %s" % message)

    def on_nick_change(self, old, new):
        """Callback when a user changes nicknames: keep counter keys up to date"""
        global STATE
        global NICK
        if (NICK != old and NICK != new and old != '<unregistered>'):
            logging.info("Changing user counters from %s to %s" % (old, new))
            if(old in STATE['counters'].keys()):
                STATE['counters'][new] = STATE['counters'][old]
                del STATE['counters'][old]
            else:
                STATE['counters'][new] = {}

    def on_part(self, channel, user, message=None):
        """"Remove counters on part, thus removing user from random $user choice"""
        if(user in STATE['counters'].keys()):
            logging.info("Removing user counters for %s " % user)
            del STATE['counters'][user]

    def on_ctcp_action(self, target, query, contents=None):
        logging.info("ctcp action target=%s query=%s contents=%s" % (target, query, contents))
        STATE['buffer'].appendleft( (target, '/me ' + contents) )

    def on_message(self, channel, sender, message, private=False):
        """Callback called when the client received a message."""
        global STATE 

        # make sure the username is initialized for counter use
        if(sender not in STATE['counters'].keys()): 
            if(sender.lower() not in CHAN.lower()):
                logging.info("Adding %s key to STATE['counters']" % sender)
                STATE['counters'][sender] = {}
                if(sender in STATE['_counters'].keys()):
                    # restore old counters
                    STATE['counters'][sender] = STATE['_counters'][sender]
                    del STATE['_counters'][sender]
        # Save timestamp of most recent message
        logging.info("Updating timestamp for %s" % sender)
        STATE['timestamp'][sender] = time.time()

        # Filter out private messages, those will be handled in on_private_message
        if(channel == NICK): return

        # Add all messages to a deque to allow for quoting user's messages
        # Store as a tuple to allow searching by user, append left for easy iteration
        STATE['buffer'].appendleft( (sender, message) )

        logging.info("Message received, channel: %s, sender: %s, message: %s" % (channel, sender, message))
        # For now, make sure that the message is addressed to this bot or is an operator
        is_op = False
        found_op = False
        logging.info("Testing for operators:")

        for word in message.split(' '):
            logging.info("testing for operators in %s" % word)
            for op in self.botbrain.OPERATORS.keys():
                if(op in word):
                    logging.info("Found %s in %s" % (op, word))
                    if(word not in STATE['counters'].keys() and word not in STATE['_counters'].keys()):
                        logging.info("Not found in %s" % (STATE['_counters'].keys()))
                        is_op = True
                        found_op = op
                    else:
                        logging.info("%s is in counters" % (word))

        if(is_op or message[0] == '!' or (len(message) > len(NICK) and NICK.lower() == message[:len(NICK)].lower())):
            # reset boredom limit when we're addressed
            STATE['boredom_limit'] = 700

            # remove the bot name/bang from the message
            if(message[0] == '!'):
                message = message[1:]
            elif(NICK.lower() == message[:len(NICK)].lower()):
                message = message[len(NICK)+1:]

            # Parse for special operators
            is_command = False
            # for op in self.botbrain.OPERATORS.keys():
            if (is_op):
                logging.info("Operator: %s" % found_op)
                # call the appropriate function in the function dictionary
                retval = self.botbrain.OPERATORS[found_op](message, sender, STATE, private)
                if (retval is not None):
                    # Send message without processing on operators
                    self.sendMessage(channel, retval, False)

            # If it's not an operator, look for a command
            if(not is_op):
                # extract the command from the message
                command = message.split()[0]
                command = command.lower()
                logging.info("Looking for command: %s" % command)
                if(command in self.botbrain.COMMANDS):
                    is_command = True
                    logging.info("Command: %s" % command)
                    retval = self.botbrain.COMMANDS[command](message, sender, STATE)
                    if (retval is not None):
                        # Send message with appriate processing
                        self.sendMessage(channel, self.preprocess_message(sender, retval), self.botbrain.PROCESSCOMMANDS[command])
                else:
                    logging.info("Can't find %s()" % command)

            # If it's not an operator and not a command, let's see if there are any factoids on the topic
            if(not is_op and not is_command):
                logging.info("Looking for factoid: %s" % message)
                factoid = self.botbrain.findFactoid(message.lower().rstrip().lstrip())
                if(factoid is not None):
                    self.sendMessage(channel, self.preprocess_message(sender, factoid))
                else:
                    # If it's not an operator, command, or factoid, look for a __confused response
                    factoid = self.botbrain.findFactoid("__confused")
                    if(factoid is not None):
                        self.sendMessage(channel, self.preprocess_message(sender, factoid))


        # If the message is not addressed to the bot, let's look for a factoid
        else:
            if(len(message) > 2):
                logging.info("Looking for factoid: %s" % message)
                factoid = self.botbrain.findFactoid(message.lower().rstrip().lstrip())
                if(factoid is not None):
                    self.sendMessage(channel, self.preprocess_message(sender, factoid))

    def preprocess_message(self, sender, message):
        """ Allow use of $nick and $user keywords in factoids etc """
        global STATE
        # First allow the bot to address who it's responding to via $nick
        message = message.replace("$nick", sender)        
        # replace any instances of $user with a random username from STATE 
        if (len(list(STATE['counters'].keys())) > 0):
            # First, attempt to pick users who have talked recently for $recentuser
            user = random.choice(list(STATE['timestamp'].keys()))
            success = False
            for i in range(100):
                while user.lower() == CHAN.lower():
                    logging.info("user is chan, rechecking")
                    user = random.choice(list(STATE['timestamp'].keys()))
                logging.info("Checking timestamp for %s" % user)
                if time.time() - LULL < STATE['timestamp'][user]:
                    logging.info("Replacing $recentuser with %s" % user)
                    message = message.replace("$recentuser", user)
                    break 
                else:
                    user = random.choice(list(STATE['timestamp'].keys()))
                    logging.info("Timestamp of %s too old" % STATE['timestamp'][user])

            # Last case, default to $user
            message = message.replace("$recentuser", "$user")

            # Don't address messages to the channel
            user = random.choice(list(STATE['counters'].keys()))
            while user.lower() == CHAN.lower():
                user = random.choice(list(STATE['counters'].keys()))
            message = message.replace("$user", user)
        return message

    def on_private_message(self, sender, message):
        logging.info("Private message received: sender: %s, message: %s" % (sender, message))
        # try to just process everything like a normal message
        self.on_message(sender, sender, NICK + ': ' + message, True)

    def save_counters(self):
        """Persist counters to file"""
        global STATE 
        if (len(list(STATE['counters'].keys())) > 0):
            pickle.dump(STATE['counters'], open('counters.p', 'wb'))

    def load_counters(self):
        """Load saved counters to a hidden state variable"""
        global STATE 
        STATE['_counters'] = pickle.load(open('counters.p', 'rb'))

    def on_raw(self, message):
        """Called on raw message (almost anything). We don't want to handle most things here."""
        global STATE 
        logging.info("on_raw - %s!" % message)

        # Look for pings. All idle processing stuff goes here.
        if("PING" in "%s" % message): 
            logging.info("PING!")

            # make sure db stays available
            if self.botbrain is not None: 
                self.botbrain.keepConnection()
                
            # check for new messages
            for message, target in self.botbrain.getMessages():
                if target is None:
                    self.sendMessage(CHAN, self.preprocess_message(NICK, message))
                else:
                    self.sendMessage(target, self.preprocess_message(NICK, message))
            
            # save current counters to file
            self.save_counters()

            # pings are a sign we're getting bored
            STATE['boredom'] += 1
            if random.randrange(STATE['boredom_limit']) < STATE['boredom']:
                # increment the limit so he gets less chatty over time
                STATE['boredom_limit'] += 500
                boredthings = ['...', '...', '!fun fact', '!recall', '!youtube me', 'office quotes']
                self.on_message(CHAN, CHAN, random.choice(boredthings))

        # Let the base client handle the raw stuff
        super(GrossmaulBot, self).on_raw(message)

# Start and connect the bot
client = GrossmaulBot(NICK, fallback_nicknames=[NICK[:-1]+"1", NICK[:-1]+"2"])
logging.info("Connecting to %s:%s" % (HOST, PORT))
client.connect(HOST, PORT, tls=True, tls_verify=False)
client.handle_forever()

