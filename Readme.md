# Super Mail Test Professional - Gold (Enterprise Edition)

SMTP-GEE is a tool to monitor mail delivery End-2-End for Nagios/Icinga or Prometheus.

It checks how long it takes to send a mail (by SMTP) and how long it takes
this mail to appear in the Inbox of the recipient (by IMAP).

Only built-in Python modules are used.

## Usage:

```
usage: smtp-gee.py [-h] --from <name> --rcpt <name> [--nagios] [--prometheus] [--except-means <int>] [--debug] [--config <file>] [--smtp_warn <sec>] [--smtp_crit <sec>] [--smtp_timeout <sec>] [--imap_warn <sec>] [--imap_crit <sec>]
                   [--imap_timeout <sec>]

Check how long it takes to send a mail (by SMTP) and how long it takes to find it in the IMAP-inbox

options:
  -h, --help            show this help message and exit

Main options:
  --from <name>         The account to send the message
  --rcpt <name>         The account to receive the message
  --nagios              output in Nagios mode
  --prometheus          output in Prometheus mode
  --except-means <int>  Map Exceptions to another returncode. Default: 2
  --debug               Debug mode
  --config <file>       alternate config-file

SMTP options:
  --smtp_warn <sec>     warning threshold to send the mail. Default: 15
  --smtp_crit <sec>     critical threshold to send the mail. Default: 30
  --smtp_timeout <sec>  timeout to stop sending a mail. Default: 30

IMAP options:
  --imap_warn <sec>     warning threshold until the mail appears in the INBOX. Default: 20
  --imap_crit <sec>     critical threshold until the mail appears in the INBOX. Default: 30
  --imap_timeout <sec>  timeout to stop waiting for a mail to appear in the INBOX (not implemented yet). Default: 30

Because e-mail is a realtime-medium and you know it!
```


### Configuration

see [config.ini.example](config.ini.example).

### Nagios (legacy)

```
./smtp-gee.py --from web.de --rcpt gmx.de --nagios
OK: (web.de->gmx.de) sent in 0.525 sec, received in INBOX in 8.125 sec|smtp=0.525;15.000;30.000 imap=8.125;20.000;30.000
```

### Prometheus

```
./smtp-gee.py --rcpt web.de --from gmx.de --prometheus
# HELP smtp_gee exports metrics about SMTP and IMAP duration
# TYPE smtp_gee gauge
smtp_gee{protocol="SMTP",from="gmx.de",rcpt="web.de",state="success",error_string=""} 0.4192631244659424
smtp_gee{protocol="IMAP",from="gmx.de",rcpt="web.de",state="success",error_string="",folder="INBOX"} 2.3448445796966553
```

Following the [KISS principle](https://en.wikipedia.org/wiki/KISS_principle), the idea is to be run by cron like this:

```crontab
*/5 * * * * /path/to/smtp-gee.py --config /path/to/config.ini --rcpt web.de --from gmx.de --prometheus | sponge /path/to/prometheus-textfile-collectors/smpt_gee_gmxde_webde.prom
``` 

the parameters `--(smtp|imap)_(warn|crit)` are completely useless with `--prometheus`, as the alarming is handled by an alert-manager.


For more information see:
https://github.com/prometheus/node_exporter#textfile-collector


# Todo:

* rewrite everything, because it's ugly (but it works).
* improve documentation :-)
* better error handling.
* add a Dockerfile (for fun)
* add a Helm-Chart for Kubernetes (for even more fun!)
* add parameter `--orgy` (working title), where all configured accounts in `config.ini` exchange e-mails with all others (maybe in parallel?).