#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Super Mail Test Professional - Gold (Enterprise Edition)"""

import smtplib
import ConfigParser
import time
import hashlib
import socket
from imaplib2 import imaplib2
import argparse
import sys
import threading
import re
import csv

from email.mime.text import MIMEText
from email.parser import Parser

# Nagios Codes
STATE_OK = 0
STATE_WARNING = 1
STATE_CRITICAL = 2
STATE_UNKNOWN = 3

class ImapIdler(threading.Thread): # {{{
    """This Class is used to create the ImapIdler Object."""

    def __init__(self, imap_server, login, password, subject_prefix, debug=False, imapfolder='INBOX'): # {{{
        threading.Thread.__init__(self)
        self.imapfolder = imapfolder
        self.subject_prefix = subject_prefix
        self.__stop = threading.Event()
        self.__debug = debug
        self.__last_id = False
        self.senders = 0

        # create empty resultdict
        self.__result_store = {}

        # create the Imap Object
        self.imapobject = imaplib2.IMAP4_SSL(imap_server)
        self.imapobject.login(login, password)
        self.imapobject.select()
    # }}}

    def run(self): # {{{
        """we override the run method from threading.Thread so it knows what to do."""
        # get last id available
        start_id = int(self.imapobject.select(self.imapfolder)[1][0])

        # well..always do that untill we stop it
        while True:
            new_id = 0
            # if we need to stop we will
            if self.__stop.isSet():
                return
            else:
                try:
                    # start IDLE with a timeout of 10 seconds
                    result = self.imapobject.idle(10)
                    # we finished IDLEING for now
                    if result[0] == 'OK':
                        if self.__debug:
                            print("%s: IMAPIdler-> Timeout or Event when IDLE!" % (str(time.time())))
                        # check if timeout or new event happened
                        if self.imapobject.response('IDLE')[1][0] == None:
                            # try to get EXISTS message untill there are no more
                            while True:
                                # get the Mail-IDs
                                response_id = self.imapobject.response('EXISTS')
                                # there are no more messages stacked
                                if response_id[1][0] == None:
                                    break
                                # if the new ID is newer overwrite new_id
                                if int(response_id[1][0]) > int(new_id):
                                    end_id = response_id[1][0]
                            if self.__debug:
                                print("%s: IMAPIdler-> IMAP-EXISTS-response: %s" % (str(time.time()), str(new_id)))
                            # parse fetched messages
                            start_id = self.parse_new_emails(start_id, end_id)
                    else:
                        print 'IMAPIdler-> Did not receive OK...strange'

                except:
                    raise
    # }}}

    def parse_new_emails(self, start_id, end_id):
        # reset last_id because possibly some emails got deleted..
        if int(end_id) < start_id or int(end_id) == start_id:
            start_id = (int(end_id)-1)
        # iterate through messages if we shall not stop yet
        while int(end_id) > start_id and not self.__stop.isSet():
            start_id += 1

            if self.__debug:
                print("%s: IMAPIdler-> parsing mailid: %s" % 
                        (str(time.time()), str(start_id)))

            # fetch the subject from the new message
            fetch_result, fetch_header = self.imapobject.fetch(start_id, 
                                        '(BODY[HEADER.FIELDS subject])')

            if self.__debug:
                print("%s: IMAPIdler-> Headers fetched: %s" % 
                        (str(time.time()), str(fetch_header)))
            # now we need to check if the subject contains the test-id
            if fetch_result == 'OK' and fetch_header[0] != None and len(fetch_header) > 2:
                # that is really crazy but the result from fetch....can be strange!
                if fetch_header[-2] == ')': 
                    header = fetch_header[-3]
                elif fetch_header[-1] == ')':
                    header = fetch_header[-2]

                if type(header).__name__ == 'tuple':
                    header = header[1]

                if header:
                    # do some substitution to get just the test_id
                    substring = 'Subject: ' + re.sub('\|', '\\\|', re.sub('\]', '\\\]',
                                            re.sub('\[', '\\\[', self.subject_prefix)))
                    my_id = re.sub(substring, '', header.strip())
                    # store the id in a dict with the current timestamp
                    if my_id in self.__result_store:
                        raise Exception('IMAPIdler-> duplicate Mail?')
                    else:
                        self.__result_store.update({ my_id : time.time() })
                        if self.__debug:
                            print("%s: IMAPIdler-> found id: %s" % (str(time.time()), my_id))
        return start_id

    def startup(self, nr_of_senders=1):
        if self.__debug:
            print("%s: IMAPIdler-> starting up Thread" % (str(time.time())))
            print("%s: IMAPIdler-> Connection will handle %s senders" % 
                                    (str(time.time()), str(nr_of_senders)))
        # start the thread
        self.start()
        self.senders = nr_of_senders

    def stop(self, force=False):
        # stop the thread if all senders are through
        if self.senders == 1 or force:
            if self.__debug:
                print("%s: IMAPIdler-> stopping Thread now" % (str(time.time())))
            self.__stop.set()
            self.imapobject.logout()
            self.join()
        else:
            if self.__debug:
                print("%s: IMAPIdler-> one sender finished." % (str(time.time())))
                print("%s: IMAPIdler-> waiting for %s more senders" % 
                                (str(time.time()), str((self.senders-1))))
            self.senders -= 1

    def get_ids(self):
        return self.__result_store
# }}}

class Account(object): # {{{
    """Account object we use for sending or fetching messages"""
    def __init__(self, configdict): # {{{
        try:
            self.name           =   configdict['name']
            self.login          =   configdict['login']
            self.password       =   configdict['password']
            self.smtp_server    =   configdict['smtp_server']
            self.imap_server    =   configdict['imap_server']
            self.email          =   configdict['email']
        except KeyError, e:
            print("you need to configure the key %s in configsection %s" % ( str(e), configdict['name'] ))
            sys.exit(255)
 

        # default values
        self.__imap_timeout     =   300
        self.__debug            =   False
        self.imap_idle          =   False
        self.connected          =   False
        self.started            =   False
        self.smtp_over_ssl      =   False

        # overwrite defaults
        if 'smtp_over_ssl' in configdict:
            self.smtp_over_ssl  =   configdict['smtp_over_ssl']
        if 'imap_idle' in configdict:
            self.imap_idle      =   True

        # subject prefix used in mails
        self.subject_prefix     =   "[SMTP-GEE] |"
    # }}}

    def send(self, recipient): # {{{
        """send a message to 'recipient'"""

        # get current timestamp
        timestamp = time.time()

        # the Message we use
        mail_template = """Hi,
this is a testmail, generated by SMTP-GEE.

sent on:   %s
sent at:   %s
sent from: %s
sent to:   %s

Cheers.
    SMTP-GEE

""" % (socket.getfqdn(), timestamp, self.email, recipient, )

        # create hash from template for tests
        test_id = hashlib.sha1(mail_template).hexdigest()

        msg = MIMEText(mail_template)

        # set sender, recipient and subject
        msg['From']     =   self.email
        msg['To']       =   recipient
        msg['Subject']  =   self.subject_prefix + test_id

        # create smtp object and send message through
        try:
            if self.smtp_over_ssl:
                if self.__debug:
                    print("%s: SMTP -> SMTP-over-SSL is used" % (str(time.time())))
                smtp_server = smtplib.SMTP_SSL( self.smtp_server )
            else:
                if self.__debug:
                    print("%s: SMTP -> non-SSL-SMTP is used. trying STARTTLS." % (str(time.time())))
                smtp_server = smtplib.SMTP( self.smtp_server )
                smtp_server.starttls()

            smtp_server.login(self.login, self.password )

            smtp_server.sendmail( self.email, recipient, msg.as_string() )
            smtp_server.quit()
            if self.__debug:
                print("%s: SMTP -> testmessage sent." % (str(time.time())))

            # return test_id for fetching the message
            return test_id
        # failed to create smtp object
        except:
            return False
    # }}}

    def prepare_startup(self, nr_of_senders=1): # {{{
        ''' helper function for IMAP IDLE. Startup IDLER thread'''
        if not self.started:
            self.started = True
            self.senders = nr_of_senders
            # startup idler if we have that functionality
            if self.imap_idle:
                self.ImapIdle(start=True)
    # }}}

    def ImapIdle(self, check_id=None, start=False): # {{{
        '''Check Imap Idle Threads or startup idler (start=True)'''

        # onle create a new idler of we are not yet connected and we are at startup
        if start and not self.connected:
            self.__idler = ImapIdler(self.imap_server, self.login, self.password,  self.subject_prefix, self.__debug)
            self.__idler.startup(self.senders)
            self.connected = True
        # if it's not the startup we need to check if the id is yet received
        elif not start:
            if check_id == None:
                raise Exception('Missing check_id')
            else:
                # set the check_start time for imap timeouts
                check_start = int(time.time())
                check_now = check_start
                # check for check_id until timeout occurs
                while (check_now - check_start) < self.__imap_timeout:
                    # call get_ids to get a list of already fetched testmails
                    results = self.__idler.get_ids()
                    if check_id in results:
                        # immediately stop if we found it
                        self.__idler.stop()
                        self.senders -= 1
                        return True, results[check_id]
                    else:
                        # try again later if not
                        time.sleep(1)
                        check_now = int(time.time())
                else:
                    # timeout occured. Stop everything.
                    if self.__debug:
                        print("%s: IMAPIdler -> Failed to fetch the Message..." 
                                                        % (str(time.time())))

                    if self.senders == 1:
                        # if we have no more senders waiting
                        self.connected = False
                    # decrease sender variable
                    self.senders -= 1
                    self.__idler.stop()
                    return False, None
    # }}}

    def ImapSearch(self, check_id): # {{{
        ''' Search for check_id in imapobject'''
        data = ['']

        # only connect if we are not yet connected
        if not self.connected:
            if self.__debug:
                print("%s: IMAP -> Starting IMAP Connection" % (str(time.time())))
                print("%s: IMAP -> Connection will handle %s senders" % 
                                    (str(time.time()), str(self.senders)))
            self.imapobject = imaplib2.IMAP4_SSL(self.imap_server)
            self.imapobject.login(self.login, self.password)
            self.connected = True

        self.imapobject.select()

        # Wait until the message is there.
        check_start = int(time.time())
        check_now = check_start

        # search for the mail-id until timeout or you got it
        while data == [''] and (check_now - check_start) < self.__imap_timeout:
            typ, data = self.imapobject.search(None, 'SUBJECT', '"%s"' % check_id)
            time.sleep(1)
            check_now = int(time.time())

        # that's the timestamp we received the testmail
        timestamp = time.time()

        if data != ['']:
            result = True
        else:
            result = False
            if self.__debug:
                print("%s: IMAP -> Failed to fetch the Message." % 
                                                    (str(time.time())))

        # the following is just for debug
        if self.__debug:
            if result:
                for num in data[0].split():
                    # fetch the complete message
                    typ, data = self.imapobject.fetch(num, '(RFC822)')

                if len(data) < 2:
                    print("%s: IMAP -> HICKUP: result is less then 2 elements?" % (str(time.time())))
                    print("%s: IMAP -> Data: %s" % (str(time.time()), str(data)))
                    data = False

            if data and result:
                if data[-1] == ')': # we need to search for the correct message...it's one field before the ')' field
                    msg = data[-2][1]
                elif data[-2] == ')':
                    msg = data[-3][1]
                else:
                    if self.__debug:
                        print("%s: IMAP -> Do not know what to use from %s" % 
                                                    (str(time.time()), str(data)))
                        print("%s: IMAP -> fallback to data[0][1]" % 
                                                    (str(time.time())))
                    msg = data[0][1]
                try:
                    headers = Parser().parsestr(msg)
                except:
                    print("%s: IMAP -> Error when parsing the message..." % 
                                                            (str(time.time())))
                else:
                    for h in headers.get_all('received'):
                        print("---")
                        print(h.strip('\n'))

        # deleting should be more sophisticated, for debugging...
        #m.store(num, '+FLAGS', '\\Deleted')

        # just close the imap connection when all senders for this account are done
        if self.senders == 1:
            if self.__debug:
                print("%s: IMAP -> Closing IMAP Connection" % (str(time.time())))
            self.imapobject.close()
            self.imapobject.logout()
        else:
            if self.__debug:
                print("%s: IMAP -> Connection waits for %s more senders" % 
                                    (str(time.time()), str(self.senders-1)))
            self.senders -= 1
        # return the results and our timestamp
        return result, timestamp
    # }}}

    def check(self, check_id): # {{{
        """check for given test-ID in IMAP Folder(s)"""
        if self.imap_idle:
            return self.ImapIdle(check_id)
        else:
            return self.ImapSearch(check_id)
    # }}}

    def set_debug(self, debug): # {{{
        """set debugging True or False"""
        self.__debug = debug

    # }}}

    def set_timeout(self, key, timeout): # {{{
        """set timeout value"""
        if key == 'imap': # I have no Idea why i can't do this with setattr...
            self.__imap_timeout = timeout
    # }}}

# }}}

class Stopwatch(object): # {{{
    """Well...a stopwatch class"""
    def __init__(self, debug=False):
        super(Stopwatch, self).__init__()
        self.__debug = debug
        self.__start = -1
        self.counter = 0

    def start(self, my_time=time.time()):
        """start the damn thing."""
        self.__start = my_time

    def stop(self, my_time=time.time()):
        """stop it. you may set a time here, too"""
        if my_time == None:
            my_time = time.time()
        self.counter = my_time - self.__start
        self.__start = -1
# }}}

if __name__ == "__main__":

    # fallback returncode
    returncode = STATE_OK

    # Variables
    perfdata = ""
    result = ""

    # Parse Options # {{{
    parser = argparse.ArgumentParser(
        description='Check how long it takes to send a mail (by SMTP) and how long it takes to find it in the IMAP-inbox',
        epilog = "Because e-mail is a realtime-medium and you know it!")


    main_parser_group = parser.add_argument_group('Main options')
    main_parser_group.add_argument('--from', dest='sender', action='store',
                    required=True,
                    metavar="<name>|<name,name>,all",
                    help='The account(s) to send the message from (must be comma separated for lists)')

    main_parser_group.add_argument('--rcpt', dest='rcpt', action='store',
                    required=True,
                    metavar="<name>|<name,name>,all",
                    help='The account(s) to receive the message on (must be comma separated for lists)')

    main_parser_group.add_argument('--output-mode', dest='outputmode', action='store',
                    required=False,
                    default='plain',
                    help='output mode (plain, nagios, csv)')

    main_parser_group.add_argument('--debug', dest='debug', action='store_true',
                    required=False,
                    default=False,
                    help='Debug mode')

    main_parser_group.add_argument('--config', dest='config_file', action='store',
                    default='config.ini',
                    metavar="<file>",
                    required=False,
                    help='alternate config-file')

    main_parser_group.add_argument('--smtp_timeout', dest='smtp_timeout', action='store',
                    required=False,
                    default=60,
                    metavar="<sec>",
                    type=int,
                    help='timeout to stop sending a mail (not implemented yet). Default: %(default)s')

    main_parser_group.add_argument('--imap_timeout', dest='imap_timeout', action='store',
                    required=False,
                    default=300,
                    metavar="<sec>",
                    type=int,
                    help='timeout to stop waiting for a mail to appear in the INBOX (not implemented yet). Default: %(default)s')

    csv_parser_group =  parser.add_argument_group('CSV options')
    csv_parser_group.add_argument('--outputfile', dest='outputfile', action='store',
                    required=False,
                    default="smtp-gee.csv",
                    metavar="FILE",
                    help='File to write CSV output to')


    smtp_parser_group = parser.add_argument_group('SMTP options for plain and nagios output')
    smtp_parser_group.add_argument('--smtp_warn', dest='smtp_warn', action='store',
                    required=False,
                    default=15,
                    metavar="<sec>",
                    type=int,
                    help='warning threshold to send the mail. Default: %(default)s')

    smtp_parser_group.add_argument('--smtp_crit', dest='smtp_crit', action='store',
                    required=False,
                    default=30,
                    metavar="<sec>",
                    type=int,
                    help='critical threshold to send the mail. Default: %(default)s')

    imap_parser_group = parser.add_argument_group('IMAP options for plain and nagios output')
    imap_parser_group.add_argument('--imap_warn', dest='imap_warn', action='store',
                    required=False,
                    default=120,
                    metavar="<sec>",
                    type=int,
                    help='warning threshold until the mail appears in the INBOX. Default: %(default)s')

    imap_parser_group.add_argument('--imap_crit', dest='imap_crit', action='store',
                    required=False,
                    default=300,
                    metavar="<sec>",
                    type=int,
                    help='critical threshold until the mail appears in the INBOX. Default: %(default)s')

    args = parser.parse_args()
    # }}}

    def execute_checks(accounts, all_sender, all_recipient, debug=False): # {{{
        senders = all_sender.split(',')
        recipients = all_recipient.split(',')
        results = {}

        if len(senders) == 1 and senders[0] == 'all':
            if senders not in accounts.keys():
                senders = accounts.keys()
            else:
                if debug:
                    print("NOTICE: using \"all\" for senders but have that as section in configfile")

        if len(recipients) == 1 and recipients[0] == 'all':
            if recipients not in accounts.keys():
                recipients = accounts.keys()
            else:
                if debug:
                    print("NOTICE: using \"all\" for recipients but have that as section in configfile")

        ### Here the real work begins  ###

        # Create the stopwatches.
        smtp_time = Stopwatch()
        imap_time = Stopwatch()

        # iterate through recipients:
        for recipient in recipients:

            # and through senders of course:
            for sender in senders:
                # set name for resultset
                resultname = sender + '-to-' + recipient
                results.update({ resultname : {} })

                # if possible startup idler
                accounts[recipient].prepare_startup(len(senders)) # we need to overgive the number of senders

                # send the mail by SMTP
                smtp_time.start()
                test_id = accounts[sender].send(accounts[recipient].email)
                smtp_time.stop()

                if test_id:
                    results[resultname].update({ 'SMTP' : True })
                    results[resultname].update({ 'ID' : test_id })
                    results[resultname].update({ 'SMTP_TIME' : smtp_time.counter })

                    if args.debug:
                        print("%s: SMTP -> Test-ID: %s" % (str(time.time()), test_id))

                    # Create the stopwatches.
                    # Receive the mail.
                    imap_time.start(time.time())
                    success, stoptime = accounts[recipient].check(test_id)
                    imap_time.stop(stoptime)
                    results[resultname].update({ 'IMAP' : success })
                    results[resultname].update({ 'IMAP_TIME' : imap_time.counter })
                else:
                    results[resultname].update({ 'SMTP' : False })
                    results[resultname].update({ 'ID' : "unknown" })
                    results[resultname].update({ 'SMTP_TIME' : smtp_time.counter })
                    results[resultname].update({ 'IMAP' : True })
                    results[resultname].update({ 'IMAP_TIME' : "0.000" })

        return results
    # }}}

    # Read Config {{{
    cparser = ConfigParser.ConfigParser()
    cparser.read(args.config_file)

    accounts = {}

    for section in cparser.sections():

        configdict = {}

        configdict.update({ 'name' : section })
        for option in cparser.options(section):
            configdict.update({ option : cparser.get(section, option) })

        accounts.update({ section : Account(configdict) })
 
        accounts[section].set_debug(args.debug)

        accounts[section].set_timeout('imap', args.imap_timeout)
    # }}}

    ### get the results
    results = execute_checks(accounts, args.sender, args.rcpt)
    resultlist = []

    # present the results
    for resultkey in results.keys():
        if args.outputmode == 'plain':
            if not results[resultkey]['SMTP']:
                print "SMTP (%s) failed" % ( resultkey )
                continue
            elif (results[resultkey]['SMTP_TIME'] >= args.smtp_crit):
                print("CRITICAL: SMTP, (%s) time to send the mail: %.3f sec." % 
                                    ( resultkey, results[resultkey]['SMTP_TIME'] ))
            elif (results[resultkey]['SMTP_TIME'] >= args.smtp_warn):
                print("WARNING: SMTP, (%s) time to send the mail: %.3f sec." % 
                                    ( resultkey, results[resultkey]['SMTP_TIME'] ))
            else:
                print("SMTP, (%s) time to send the mail: %.3f sec." % 
                                    ( resultkey, results[resultkey]['SMTP_TIME'] ))

            if not results[resultkey]['IMAP']:
                print("IMAP (%s) failed. the mail could not be fetched within %.3f sec." % 
                                    ( resultkey, results[resultkey]['IMAP_TIME'] ))
            elif (results[resultkey]['IMAP_TIME'] >= args.imap_crit):
                print("CRITICAL: IMAP, (%s) time until the mail appeared in the destination INBOX: %.3f sec." % 
                                    ( resultkey, results[resultkey]['IMAP_TIME'] ))
            elif (results[resultkey]['IMAP_TIME'] >= args.imap_warn):
                print("WARNING: IMAP, (%s) time until the mail appeared in the destination INBOX: %.3f sec." % 
                                    ( resultkey, results[resultkey]['IMAP_TIME'] ))
            else:
                print("IMAP, (%s) time until the mail appeared in the destination INBOX: %.3f sec." % 
                                    ( resultkey, results[resultkey]['IMAP_TIME'] ))

        elif args.outputmode == 'plain':
            # Nagios output
            # this could be beautified...
            nagios_code = ('OK', 'WARNING', 'CRITICAL', 'UNKNOWN' )

            # Nagios output {{{
            if not results[resultkey]['SMTP']: 
                returncode = STATE_CRITICAL
                result += "%s: (%s) SMTP failed in %.3f sec " % ( nagios_code[returncode], 
                resultkey, results[resultkey]['SMTP_TIME'], )
            elif (results[resultkey]['SMTP_TIME'] >= args.smtp_crit):
                returncode = STATE_CRITICAL
                result += "%s: (%s) SMTP in %.3f sec " % ( nagios_code[returncode], 
                resultkey, results[resultkey]['SMTP_TIME'], )
            elif (results[resultkey]['SMTP_TIME'] >= args.smtp_warn):
                returncode = STATE_WARNING
                result += "%s: (%s) SMTP in %.3f sec " % ( nagios_code[returncode], 
                resultkey, results[resultkey]['SMTP_TIME'], )

            if not results[resultkey]['IMAP']:
                returncode = STATE_CRITICAL
                result += "%s: (%s) IMAP NOT received in %.3f sec " % ( nagios_code[returncode], 
                resultkey, results[resultkey]['IMAP_TIME'],  )
            elif (results[resultkey]['IMAP_TIME'] >= args.imap_crit):
                returncode = STATE_CRITICAL
                result += "%s: (%s) IMAP received in %.3f sec " % ( nagios_code[returncode], 
                resultkey, results[resultkey]['IMAP_TIME'],  )
            elif (results[resultkey]['IMAP_TIME'] >= args.imap_warn):
                if returncode < STATE_CRITICAL:
                    returncode = STATE_WARNING
                result += "%s: (%s) IMAP received in %.3f sec " % ( nagios_code[returncode], 
                resultkey, results[resultkey]['IMAP_TIME'],  )
            # }}}

            perfdata += " %s_smtp=%.3f;%.3f;%.3f %s_imap=%.3f;%.3f;%.3f" % ( resultkey, results[resultkey]['SMTP_TIME'],
            args.smtp_warn, args.smtp_crit, resultkey, results[resultkey]['IMAP_TIME'], args.imap_warn, args.imap_crit )

        elif args.outputmode == 'csv':
            resultlist.append({ 'name' : resultkey, 'SMTP_TIME' : results[resultkey]['SMTP_TIME'], 'IMAP_TIME' : results[resultkey]['IMAP_TIME'], 
                'SMTP_SUCCESS' : results[resultkey]['SMTP'], 'IMAP_SUCCESS' : results[resultkey]['IMAP'] })

    if args.outputmode == 'nagios':
        if result == "":
            result = "OK: all tests were successfull "
        print("%s|%s" % (result, perfdata))
        sys.exit(returncode)
    elif args.outputmode == 'csv':
        with open(args.outputfile, 'wb') as f:
        # Using dictionary keys as fieldnames for the CSV file header
            writer = csv.DictWriter(f, resultlist[0].keys())
            writer.writeheader()
            for d in resultlist:
                writer.writerow(d)

## vim:fdm=marker:ts=4:sw=4:sts=4:ai:sta:et
