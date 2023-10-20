#!/usr/bin/env python3

import smtplib
from datetime import datetime
import argparse


class MailMe:

    def __init__(self, user, pwd):

        self.user = user
        self.pwd = pwd

    def __prepare_and_send(self, recipient, subject, body):

        FROM = self.user
        TO = recipient if type(recipient) is list else [recipient]
        SUBJECT = subject
        TEXT = body

        # Prepare actual message
        message = """From: %s\nTo: %s\nSubject: %s\n\n%s \n\n\n Time: %s
		""" % (FROM, ", ".join(TO), SUBJECT, TEXT, str(datetime.now()))

        try:
            server = smtplib.SMTP("smtp.gmail.com", 587)
            server.ehlo()
            server.starttls()
            server.login(self.user, self.pwd)
            server.sendmail(FROM, TO, message)
            server.close()
            print("successfully sent the mail")
        except Exception as e:
            print("failed to send mail")

    def send_email(self, recipient, subject, body):

        self.__prepare_and_send(recipient, subject, body)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument('msg', help="Mail message (Body)", type=str)
    parser.add_argument('-s', '--subject', help="MAil subject", type=str)
    parser.add_argument('-d', '--dest', help="Destination, recipient", type=str)

    parser.add_argument('-u', '--user', help="Source Mail", type=str)
    parser.add_argument('-p', '--passw',
                        help="Source email password",
                        type=str,
                        required=True)

    args = parser.parse_args()
    mail_me = MailMe(user=args.user,
                     pwd=args.passw)

    mail_me.send_email(recipient=args.dest, subject=args.subject, body=args.msg)


if __name__ == "__main__":
    main()
