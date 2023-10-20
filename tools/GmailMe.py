#!/usr/bin/env python3

import smtplib
from datetime import datetime
import argparse
from typing import List, Union

class GMailMe:
    """
    Class for sending email via Gmail
    """
    
    def __init__(self, user: str, pwd: str) -> None:
        self.user = user
        self.pwd = pwd
    
    def __prepare_and_send(self, recipient: Union[str, List[str]], subject: str, body: str) -> None:
        """
        Private method to prepare and send the email
        """
        
        FROM = self.user
        TO = recipient if isinstance(recipient, list) else [recipient]
        SUBJECT = subject
        TEXT = body
        
        # Prepare the actual message
        message = f"""From: {FROM}\nTo: {', '.join(TO)}\nSubject: {SUBJECT}\n\n{TEXT}\n\n\nTime: {datetime.now()}"""
        
        try:
            server = smtplib.SMTP("smtp.gmail.com", 587)
            server.ehlo()
            server.starttls()
            server.login(self.user, self.pwd)
            server.sendmail(FROM, TO, message)
            server.close()
            print("Successfully sent the mail.")
        except Exception as e:
            print(f"Failed to send mail due to: {e}")
            
    def send_email(self, recipient: Union[str, List[str]], subject: str, body: str) -> None:
        """
        Public method to send the email
        """
        self.__prepare_and_send(recipient, subject, body)

def main() -> None:
    parser = argparse.ArgumentParser()
    
    parser.add_argument('msg', help="Mail message (Body)", type=str)
    parser.add_argument('-s', '--subject', help="Mail subject", type=str)
    parser.add_argument('-d', '--dest', help="Destination, recipient", type=str)
    parser.add_argument('-u', '--user', help="Source Mail", type=str)
    parser.add_argument('-p', '--passw', help="Source email password", type=str, required=True)
    
    args = parser.parse_args()
    
    mail_me = GMailMe(user=args.user, pwd=args.passw)
    mail_me.send_email(recipient=args.dest, subject=args.subject, body=args.msg)

if __name__ == "__main__":
    main()
