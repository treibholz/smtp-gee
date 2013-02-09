#!/usr/bin/python
# -*- coding: utf-8 -*-

import smtplib
import ConfigParser 
from email.mime.text import MIMEText


class Account(object): # {{{
    """docstring for Account"""
    def __init__(self, name, login=False, password=False, smtp_server="localhost", imap_server="localhost"): # {{{
        super(Account, self).__init__()
        self.name           =   name
        self.login          =   login
        self.password       =   password
        self.smtp_server    =   smtp_server
        self.imap_server    =   imap_server
        self.email          =   login

    # }}}

    def send(self, recipient): # {{{
        """docstring for send"""

        msg = MIMEText("Test")

        msg['From']     =   self.email
        msg['To']       =   recipient.email
        msg['Subject']  =   "[Testmail] | "

        s = smtplib.SMTP( self.smtp_server )
        s.set_debuglevel(2)
        s.starttls()
        s.login(self.login, self.password )

        s.sendmail( self.email, recipient.email, msg.as_string() )
        s.quit()

    # }}}

# }}}


if __name__ == "__main__":


    c = ConfigParser.ConfigParser()
    c.read('config.ini')

    a={}

    for s in c.sections():
        a[s] = Account(s)

        # This has to be more easy...
        a[s].smtp_server = c.get(s, 'smtp_server')
        a[s].imap_server = c.get(s, 'imap_server')
        a[s].password    = c.get(s, 'password')
        a[s].login       = c.get(s, 'login')
        a[s].email       = c.get(s, 'email')



#    gmx.send(mailcom)

    a['gmx.de'].send(a['mail.com'])

## vim:fdm=marker:ts=4:sw=4:sts=4:ai:sta:et
