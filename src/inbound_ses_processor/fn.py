import boto3
import os
import aws_lambda_logging
import logging
from email.parser import Parser

MAIL_BUCKET = os.getenv("mail_bucket_name", "")
MAIL_BUCKET_REGION = os.getenv("mail_bucket_region", os.environ["AWS_DEFAULT_REGION"])
MAIL_DOMAIN = os.getenv("mail_domain", "")
LOG_LEVEL = os.getenv("log_level", "INFO")

logger = logging.getLogger()


def parse_email_content(msg, s3_handle, message_id):
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
        attach_file_data = msg.get_payload(decode=True)
        s3_handle.put_object(
            Body=attach_file_data,
            Bucket=MAIL_BUCKET,
            Key=f"@attachments/{message_id}/{attach_file_name}",
        )

    else:
        pass


def handler(event, context):
    aws_lambda_logging.setup(level=LOG_LEVEL, boto_level="CRITICAL")
    s3 = boto3.client("s3", region_name=MAIL_BUCKET_REGION)
    logger.debug(event)

    ses_notification = event["Records"][0]["ses"]
    message_id = ses_notification["mail"]["messageId"]
    receipt = ses_notification["receipt"]
    logger.info({"message_id": f"{message_id}"})
    logger.info({"receipt": f"{receipt}"})

    num_recipients = len(receipt["recipients"])
    recipient_prefixes = [x.split("@")[0] for x in receipt["recipients"]]
    copy_source = {"Bucket": MAIL_BUCKET, "Key": message_id}
    for recipient_prefix in recipient_prefixes:
        s3.copy_object(
            CopySource=copy_source,
            Bucket=MAIL_BUCKET,
            Key=f"{recipient_prefix}/cur/{message_id}",
        )

    data = s3.get_object(Bucket=MAIL_BUCKET, Key=f"{message_id}")
    contents_decoded = data["Body"].read().decode('utf-8')
    msg = Parser().parsestr(contents_decoded)
    parse_email_content(msg, s3, message_id)
    
    s3.delete_object(Bucket=MAIL_BUCKET, Key=message_id)
