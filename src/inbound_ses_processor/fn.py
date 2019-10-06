import boto3
import os
import aws_lambda_logging
import logging
from email.parser import Parser

MAIL_BUCKET = os.getenv("mail_bucket_name", "")
MAIL_BUCKET_REGION = os.getenv("mail_bucket_region", os.environ["AWS_DEFAULT_REGION"])
MAIL_DOMAIN = os.getenv("mail_domain", "")
LOG_LEVEL = os.getenv("log_level", "INFO")
ACCEPT_FROM = os.getenv("accept_from", "")

logger = logging.getLogger()


def parse_email_content(msg, s3_handle, message_id):
    """If this is a multipart message, recursively iterate through each
    part, extracting all attachments and uploading each to a message-specific
    prefix within an attachments prefix.

    Based on example from:
        https://www.dev2qa.com/python-parse-emails-and-attachments-from-pop3-server-example/
    """
    # get message content type.
    content_type = msg.get_content_type().lower()
    logger.info(content_type)

    # if the message part is text part.
    if content_type == "text/plain" or content_type == "text/html":
        pass
    # if this message part is still multipart such as 'multipart/mixed','multipart/alternative','multipart/related'
    elif content_type.startswith("multipart"):
        # get multiple part list.
        body_msg_list = msg.get_payload()
        # loop in the multiple part list.
        for body_msg in body_msg_list:
            # parse each message part.
            parse_email_content(body_msg, s3_handle, message_id)
    # if this message part is an attachment part that means it is a attached file.
    elif content_type.startswith("image") or content_type.startswith("application"):
        # get message header 'Content-Disposition''s value and parse out attached file name.
        attach_file_info_string = msg.get("Content-Disposition")
        prefix = 'filename="'
        pos = attach_file_info_string.find(prefix)
        attach_file_name = attach_file_info_string[
            pos + len(prefix) : len(attach_file_info_string) - 1
        ]

        # get attached file content.
        try:
            attach_file_data = msg.get_payload(decode=True)
            s3_handle.put_object(
                Body=attach_file_data,
                Bucket=MAIL_BUCKET,
                Key=f"@attachments/{message_id}/{attach_file_name}",
            )
        except Exception as e:
            logger.error(
                {
                    f"Failed to extract and upload to s3 '{message_id}/{attach_file_name}'": f"{repr(e)}"
                }
            )
            raise e

    else:
        pass


def handler(event, context):
    """Main event handler.  Sets up logging, parses relevent info from SES
    event notification, shuffles message object to relevant prefixes, and
    attempts to process attachment(s) in inbound messages."""
    # Set up logging
    aws_lambda_logging.setup(level=LOG_LEVEL, boto_level="CRITICAL")
    logger.debug(event)
    # Set up s3 client
    s3 = boto3.client("s3", region_name=MAIL_BUCKET_REGION)

    # Extract relevant values from the record and log them
    ses_notification = event["Records"][0]["ses"]
    message_id = ses_notification["mail"]["messageId"]
    mail_from = ses_notification["mail"]["source"]
    receipt = ses_notification["receipt"]
    accepted_senders = ACCEPT_FROM.split("|")
    logger.info({"message_id": message_id})
    logger.info({"receipt": receipt})
    logger.info({"mail_from": mail_from})

    if mail_from in accepted_senders or accepted_senders == [""]:
        logger.info("mail_from in accepted_senders")
        # Parse recipient(s) so that we can place the message in recipient-specific prefixes
        num_recipients = len(receipt["recipients"])
        recipient_prefixes = [x.split("@")[0] for x in receipt["recipients"]]
        copy_source = {"Bucket": MAIL_BUCKET, "Key": message_id}
        # Loop through parsed recipients and copy message to each prefix
        for recipient_prefix in recipient_prefixes:
            try:
                s3.copy_object(
                    CopySource=copy_source,
                    Bucket=MAIL_BUCKET,
                    Key=f"{recipient_prefix}/cur/{message_id}",
                )
            except Exception as e:
                logger.error(
                    {
                        f"Exception caught trying to copy '{message_id}' to '{recipient_prefix}/cur/{message_id}'": f"{repr(e)}"
                    }
                )

        # Attempt to download the message locally and parse its contents
        try:
            data = s3.get_object(Bucket=MAIL_BUCKET, Key=f"{message_id}")
            contents_decoded = data["Body"].read().decode("utf-8")
            msg = Parser().parsestr(contents_decoded)
            parse_email_content(msg, s3, message_id)
        except Exception as e:
            logger.error(
                {
                    f"Exception caught trying to parse message '{message_id}'": f"{repr(e)}"
                }
            )
            raise e
    else:
        logger.info("mail_from not in accepted_senders")

    # In either case, we want to delete the inbound object
    try:
        s3.delete_object(Bucket=MAIL_BUCKET, Key=message_id)
        logger.info({"Object deleted": f"{message_id}"})
    except Exception as e:
        logger.error(
            {f"Exception caught trying to delete_object '{message_id}'": f"{repr(e)}"}
        )
        raise e
