#!/usr/bin/python
# -*- coding: utf-8 -*-

import smtplib
import ConfigParser
import time
import hashlib
import socket
import imaplib2
import argparse
import sys
import threading
import re

from email.mime.text import MIMEText
from email.parser import Parser

class ImapIdler(threading.Thread): # {{{

    def __init__(self, imap_server, login, password, subject_prefix, debug=False, imapfolder='INBOX'):
        threading.Thread.__init__(self)
        self.imapfolder = imapfolder
        self.subject_prefix = subject_prefix
        self.__stop = threading.Event()
        self.__debug = debug
        self.__last_id = False
        self.idler_count = 0

        self.__result_store = {}

        self.imapobject = imaplib2.IMAP4_SSL(imap_server)

        self.imapobject.login(login, password)
        self.imapobject.select()


    def run(self):
        # fetch last ids available
        self.__last_id = int(self.imapobject.select(self.imapfolder)[1][0])

        while True:
            new_id = 0
            if self.__stop.isSet():
                return
            else:
                try:
                    result = self.imapobject.idle(10)
                    if result[0] == 'OK':
                        if self.__debug:
                            print 'ImapIdler-> Timeout or Event when IDLE!'
                        if self.imapobject.response('IDLE')[1][0] == None:
                            while True:
                                response_id = self.imapobject.response('EXISTS')
                                if response_id[1][0] == None:
                                    break
                                if int(response_id[1][0]) > int(new_id):
                                    new_id = response_id[1][0]
                            if self.__debug:
                                print 'ImapIdler-> IMAP-EXISTS-response: ' + str(new_id)
                            self.parse_new_emails(new_id)

                except:
                    raise

    def parse_new_emails(self, new_id):
        if int(new_id) < self.__last_id or int(new_id) == self.__last_id: # possibly some emails got deleted..
            self.__last_id == (int(new_id)-1)
        while int(new_id) > self.__last_id and not self.__stop.isSet():
            self.__last_id += 1
            test_id = str(self.__last_id)

            if self.__debug:
                print "ImapIdler-> parsing mailid: " + test_id

            fetch_result, fetch_header = self.imapobject.fetch(test_id, '(BODY[HEADER.FIELDS subject])')

            if self.__debug:
                print 'ImapIdler-> Headers fetched: ' + str(fetch_header)
            if fetch_result == 'OK' and fetch_header[0] != None and len(fetch_header) > 2:
                if fetch_header[-2] == ')': # that is really crazy but the result from fetch....can be strange!
                    header = fetch_header[-3]
                elif fetch_header[-1] == ')':
                    header = fetch_header[-2]

                if type(header).__name__ == 'tuple':
                    header = header[1]

                if header:
                    substring = 'Subject: ' + re.sub('\|','\\\|',re.sub('\]','\\\]',re.sub('\[','\\\[',self.subject_prefix)))
                    my_id = re.sub(substring,'',header.strip())
                    if my_id in self.__result_store:
                        raise Exception('ImapIdler-> duplicate Mail?')
                    else:
                        if self.__debug:
                            print "ImapIdler-> found id: " + my_id
                        self.__result_store.update({ my_id : time.time() })

    def startup(self, nr_of_senders=1):
        if self.__debug:
            print "ImapIdler-> starting up Thread"
            print "ImapIdler-> will wait for " + str(nr_of_senders) + " senders to complete"
        self.start()
        self.idler_count = nr_of_senders

    def stop(self, force=False):
        if self.idler_count == 1 or force:
            if self.__debug:
                print "ImapIdler-> stoping Thread now"
            self.__stop.set()
            self.imapobject.logout()
            self.join()
        else:
            if self.__debug:
                print 'ImapIdler-> thread_waiter: ' + str((self.idler_count-1))
            self.idler_count -= 1

    def get_ids(self):
        return self.__result_store
# }}}

class Account(object): # {{{
    """docstring for Account"""
    def __init__(self, configdict): # {{{
        try:
            self.name           =   configdict['name']
            self.login          =   configdict['login']
            self.password       =   configdict['password']
            self.smtp_server    =   configdict['smtp_server']
            self.imap_server    =   configdict['imap_server']
            self.email          =   configdict['email']
        except KeyError, e:
            print "you need to configure the key " + str(e) + "in configsection " + configdict['name']
            sys.exit(255)
 

        # default values
        self.__idler              =   None
        self.__imap_timeout     =   300
        self.__debug            =   False
        self.imap_idle          =   False
        self.smtp_over_ssl      =   False

        # overwrite defaults
        if 'smtp_over_ssl' in configdict:
            self.smtp_over_ssl  =   configdict['smtp_over_ssl']
        if 'imap_idle' in configdict:
            self.imap_idle      =   True

        # check_subject prefix
        self.subject_prefix     =   "[SMTP-GEE] |"
    # }}}

    def send(self, recipient): # {{{
        """docstring for send"""

        timestamp = time.time()

        payload = """Hi,
this is a testmail, generated by SMTP-GEE.

sent on:   %s
sent at:   %s
sent from: %s
sent to:   %s

Cheers.
    SMTP-GEE

""" % (socket.getfqdn(), timestamp, self.email, recipient, )


        test_id = hashlib.sha1(payload).hexdigest()


        msg = MIMEText(payload)

        msg['From']     =   self.email
        msg['To']       =   recipient
        msg['Subject']  =   self.subject_prefix + test_id

        try:
            if self.smtp_over_ssl:
                if self.__debug: print "SMTP-over-SSL is used"
                s = smtplib.SMTP_SSL( self.smtp_server )
            else:
                if self.__debug: print "SMTP is used"
                s = smtplib.SMTP( self.smtp_server )
                s.starttls()

            #s.set_debuglevel(2)
            s.login(self.login, self.password )

            s.sendmail( self.email, recipient, msg.as_string() )
            s.quit()

            return test_id

        except:
            return False


    # }}}

    def start_idle(self, nr_of_senders=1): # {{{
        ''' helper function for IMAP IDLE. Startup IDLER thread'''
        if self.imap_idle:
            self.ImapIdle(start=True, nr_of_senders=nr_of_senders)
    # }}}

    def ImapIdle(self, check_id=None, start=False, nr_of_senders=1): # {{{
        '''Check Imap Idle Threads or startup idler (start=True)'''
        if start and self.__idler is None:
            self.__idler = ImapIdler(self.imap_server, self.login, self.password,  self.subject_prefix, self.__debug)
            self.__idler.startup(nr_of_senders)
        elif not start:
            if check_id == None:
                raise Exception('Missing check_id')
            else:
                check_start = int(time.time())
                check_now = check_start
                while (check_now - check_start) < self.__imap_timeout:
                    results = self.__idler.get_ids()
                    if check_id in results:
                        self.__idler.stop()
                        return True, results[check_id]
                    else:
                        time.sleep(1)
                        check_now = int(time.time())
                else:
                    self.__idler.stop()
                    self.__idler.join()
                    return False, None
    # }}}

    def ImapSearch(self, imapobject, check_id): # {{{
        ''' Search for check_id in imapobject'''
        data=[]

        # Wait until the message is there.
        check_start = int(time.time())
        check_now = check_start
        while data == [] and (check_now - check_start) < self.__imap_timeout:
            typ, data = imapobject.search(None, 'SUBJECT', '"%s"' % check_id)
            time.sleep(1)
            check_now = int(time.time())

        timestamp = time.time()

        if data != []:
            result = True
            for num in data[0].split():
                typ, data = imapobject.fetch(num, '(RFC822)')


            if self.__debug:
                if len(data) < 2:
                    print "result is less then 2 elements"
                    print str(data)

            if data[-1] == ')': # that is really crazy but the result from fetch....can be strange!
                msg = data[-2][1]
            elif data[-2] == ')':
                msg = data[-3][1]
            else:
                if self.__debug:
                    print "Do not know what to use from " + str(data)
                    print "fallback to data[0][1]"
                msg = data[0][1]

            headers = Parser().parsestr(msg)

            if self.__debug:
                for h in headers.get_all('received'):
                    print "---"
                    print h.strip('\n')
        else:
            result = False

        # deleting should be more sophisticated, for debugging...
        #m.store(num, '+FLAGS', '\\Deleted')
        imapobject.close()
        imapobject.logout()
        return result, timestamp
    # }}}

    def check(self, check_id): # {{{
        """check for given test-ID in IMAP Folder(s)"""
        if self.imap_idle:
            return self.ImapIdle(check_id)
        else:
            m = imaplib2.IMAP4_SSL(self.imap_server)

            m.login(self.login, self.password)
            m.select()

            return self.ImapSearch(m, check_id)
    # }}}

    def set_debug(self, debug): # {{{
        """docstring for set_debug"""
        self.__debug = debug

    # }}}

    def set_timeout(self, key, timeout): # {{{
        """set timeout value"""
        if key == 'imap': # I have no Idea why i can't do this with setattr...
            self.__imap_timeout = timeout
    # }}}

# }}}

class Stopwatch(object): # {{{
    """docstring for Stopwatch"""
    def __init__(self, debug=False):
        super(Stopwatch, self).__init__()
        self.__debug = debug
        self.__start   = -1
        self.counter = 0

    def start(self, my_time=time.time()):
        """docstring for start"""
        self.__start = my_time

    def stop(self, my_time=time.time()):
        """docstring for stop"""
        if my_time == None:
            my_time = time.time()
        self.counter += my_time - self.__start
        self.__start  = -1
# }}}

if __name__ == "__main__":

    # fallback returncode
    returncode = 0

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

    main_parser_group.add_argument('--nagios', dest='nagios', action='store_true',
                    required=False,
                    default=False,
                    help='output in Nagios mode')

    main_parser_group.add_argument('--debug', dest='debug', action='store_true',
                    required=False,
                    default=False,
                    help='Debug mode')

    main_parser_group.add_argument('--config',dest='config_file', action='store',
                    default='config.ini',
                    metavar="<file>",
                    required=False,
                    help='alternate config-file')


    smtp_parser_group = parser.add_argument_group('SMTP options')
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

    smtp_parser_group.add_argument('--smtp_timeout', dest='smtp_timeout', action='store',
                    required=False,
                    default=60,
                    metavar="<sec>",
                    type=int,
                    help='timeout to stop sending a mail (not implemented yet). Default: %(default)s')


    imap_parser_group = parser.add_argument_group('IMAP options')
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

    imap_parser_group.add_argument('--imap_timeout', dest='imap_timeout', action='store',
                    required=False,
                    default=300,
                    metavar="<sec>",
                    type=int,
                    help='timeout to stop waiting for a mail to appear in the INBOX (not implemented yet). Default: %(default)s')

    args = parser.parse_args()

    # }}}

    def execute_checks(accounts, all_sender, all_recipient, debug=False): # {{{
        senders = all_sender.split(',')
        recipients = all_recipient.split()
        results = {}


        if len(senders) == 1 and senders[0] == 'all':
            if senders not in accounts.keys():
                senders = accounts.keys()
            else:
                if debug:
                    print "NOTICE: using \"all\" for senders but have that as section in configfile"

        if len(recipients) == 1 and recipients[0] == 'all':
            if recipients not in accounts.keys():
                recipients = accounts.keys()
            else:
                if debug:
                    print "NOTICE: using \"all\" for recipients but have that as section in configfile"

        ### Here the real work begins  ###
        for sender in senders:
            # Create the stopwatches.
            smtp_time = Stopwatch()

            for recipient in recipients:
                resultname = sender + '->' + recipient
                results.update({ resultname : {} })

                # if possible startup idler
                accounts[recipient].start_idle(len(senders)) # we need to overgive the number of senders

                # send the mail by SMTP
                smtp_time.start()
                test_id = accounts[sender].send(accounts[recipient].email)
                smtp_time.stop()

                if test_id:
                    results[resultname].update({ 'SMTP' : True })
                    results[resultname].update({ 'ID' : test_id })
                    results[resultname].update({ 'SMTP_TIME' : smtp_time.counter })

                    if args.debug:
                        print "Test-ID: " + test_id

                    # Create the stopwatches.
                    imap_time = Stopwatch()
                    # Receive the mail.
                    imap_time.start()
                    success, stoptime = accounts[recipient].check(test_id)
                    imap_time.stop(stoptime)
                    results[resultname].update({ 'IMAP' : success })
                    results[resultname].update({ 'IMAP_TIME' : imap_time.counter })
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

    # present the results
    for resultkey in results.keys():
        if not args.nagios:
            if results[resultkey]['SMTP'] and results[resultkey]['IMAP']:
                # Default output
                print "SMTP, (%s) time to send the mail: %.3f sec." % (resultkey, results[resultkey]['SMTP_TIME'], )
                print "IMAP, (%s) time until the mail appeared in the destination INBOX: %.3f sec." % (resultkey, results[resultkey]['IMAP_TIME'], )
            else:
                print "SMTP, (%s) time to send the mail: %.3f sec." % (resultkey, results[resultkey]['SMTP_TIME'], )
                print "IMAP, (%s) the mail could not be fetched within %.3f sec." % (resultkey, results[resultkey]['IMAP_TIME'], )
        else:

            # Nagios output
            # this could be beautified...
            nagios_code = ('OK', 'WARNING', 'CRITICAL', 'UNKNOWN' )

            if   ((results[resultkey]['SMTP_TIME'] >= args.smtp_crit) or (results[resultkey]['IMAP_TIME'] >= args.imap_crit)):
                returncode = 2
            elif ((results[resultkey]['SMTP_TIME'] >= args.smtp_warn) or (results[resultkey]['IMAP_TIME'] >= args.imap_warn)):
                if returncode < 1:
                    returncode = 1

            if results[resultkey]['SMTP'] or not results[resultkey]['IMAP']: # if it failed
                returncode = 2
                nagios_template="%s: (%s) SMTP failed in %.3f sec, NOT received in %.3f sec|smtp=%.3f;%.3f;%.3f, imap=%.3f;%.3f;%.3f"
            else:
                nagios_template="%s: (%s) sent in %.3f sec, received in %.3f sec|smtp=%.3f;%.3f;%.3f, imap=%.3f;%.3f;%.3f"

            print nagios_template % (
                nagios_code[returncode],
                resultkey,
                results[resultkey]['SMTP_TIME'],
                results[resultkey]['IMAP_TIME'],
                results[resultkey]['SMTP_TIME'],
                args.smtp_warn,
                args.smtp_crit,
                results[resultkey]['IMAP_TIME'],
                args.imap_warn,
                args.imap_crit,
            )

    if args.nagios:
        sys.exit(returncode)

## vim:fdm=marker:ts=4:sw=4:sts=4:ai:sta:et
