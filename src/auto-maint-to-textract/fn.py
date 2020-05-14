#!/usr/bin/env python

import aws_lambda_logging
import boto3
import json
import logging
import os
import re

LOG_LEVEL = os.getenv("log_level", "INFO")
MAIL_BUCKET = os.getenv("mail_bucket_name", "")
MAIL_BUCKET_REGION = os.getenv("mail_bucket_region", os.environ["AWS_DEFAULT_REGION"])

logger = logging.getLogger()


def get_kv_map(file_name):
    """Uses the AWS Textract service to get a mapping of data values
    within the document then returns a set of key-value pairs
    based on a parsing of the data structure returned by Textract.

    Args:
        file_name: String indicating absolute path to a file to be sent to Textract.

    Returns:
        key_map:  Map of Textract-derived keys within the document.
        value_map:  Map of Textract-derived values within the document.
        block_map: Map of Textract-derived blocks within the document.

    """
    with open(file_name, "rb") as fp:
        img_test = fp.read()
        bytes_test = bytearray(img_test)
        logging.debug("Image loaded", file_name)

        # process using image bytes
        client = boto3.client("textract")
        response = client.analyze_document(
            Document={"Bytes": bytes_test}, FeatureTypes=["FORMS"]
        )

        # Get the text blocks
        blocks = response["Blocks"]

        # get key and value maps
        key_map = {}
        value_map = {}
        block_map = {}
        for block in blocks:
            block_id = block["Id"].strip()
            block_map[block_id] = block
            if block["BlockType"] == "KEY_VALUE_SET":
                if "KEY" in block["EntityTypes"]:
                    key_map[block_id] = block
                else:
                    value_map[block_id] = block

        return key_map, value_map, block_map


def get_kv_relationship(key_map, value_map, block_map):
    """Get key-value relationships from Textract-returned parse data.

    Args:
        key_map:  Map of Textract-derived keys within the document.
        value_map:  Map of Textract-derived values within the document.
        block_map: Map of Textract-derived blocks within the document.

    Returns:
        Dict of key-value matched values.

    """
    kvs = {}
    for block_id, key_block in key_map.items():
        value_block = find_value_block(key_block, value_map)
        key = get_text(key_block, block_map)
        val = get_text(value_block, block_map)
        kvs[key] = val

    return kvs


def find_value_block(key_block, value_map):
    """Finds a value_block for a given key_block from value_map.

    Args:
        key_block:  Key block.
        value_map:  Map of values.

    Returns:
        Matching value block.

    """
    for relationship in key_block["Relationships"]:
        if relationship["Type"] == "VALUE":
            for value_id in relationship["Ids"]:
                value_block = value_map[value_id]

    return value_block


def get_text(result, blocks_map):
    """Gets the text result from a hierarchical representation
    of a data element within the parsed document.

    Args:
        result: Textract API response.
        blocks_map: Textract-derived blocks from parsed document.

    Returns:
        Embedded text from element within a block.

    """
    text = ""
    if "Relationships" in result:
        for relationship in result["Relationships"]:
            if relationship["Type"] == "CHILD":
                for child_id in relationship["Ids"]:
                    word = blocks_map[child_id]
                    if word["BlockType"] == "WORD":
                        text += word["Text"] + " "
                    if word["BlockType"] == "SELECTION_ELEMENT":
                        if word["SelectionStatus"] == "SELECTED":
                            text += "X "

    return text


def marshal_response(kvs):
    """Implementation-specific.  Based on document structure,
    pull out the relevant parts and return a dict that is
    useful to the case at hand.

    A better implementation of this would be to put this into an
    abstract base class that must be re-implemented for any given use-case.

    Args:
        kvs:  Dict of Textract-derived key-values

    Returns:
        Conformed dict of key-value pairs.

    """
    ret = {}
    ret["Description"] = search_value(kvs, "description").strip()
    ret["Vin"] = search_value(kvs, "vin").strip()
    ret["Vehicle"] = search_value(kvs, "vehicle").strip()
    ret["Odometer"] = re.findall(r"[\d]{1,7}", search_value(kvs, "odometer"))[0].strip()
    ret["Date"] = search_value(kvs, "invoiced").strip()
    ret["Amount"] = search_value(
        kvs, r"(?:^|(?<= ))(american|discover|visa|mastercard)(?:(?= )|$)"
    ).strip()
    ret["Tax"] = search_value(kvs, "5.3%").strip()

    return ret


def search_value(kvs, search_key):
    """Searches for a matching key (case-insensitive)
    among all keys in a provided dict.

    Args:
        kvs:  Key-value dict.
        search_key:  Value to search amongst keys for.

    Returns:
        Matching key if found, else None.

    """
    for key, value in kvs.items():
        if re.search(search_key, key, re.IGNORECASE):
            return value

    return None


def handler(event, context):
    """Main function handler.

    Args:
        event: AWS event
        context:  Lambda context

    """
    # Set up logging
    aws_lambda_logging.setup(level=LOG_LEVEL, boto_level="CRITICAL")
    logger.debug(event)

    # Set up S3 client
    s3 = boto3.client("s3", region_name=MAIL_BUCKET_REGION)

    attachment_prefixes_serialized = event["Records"][0]["Sns"]["MessageAttributes"][
        "attachments"
    ]["Value"]
    attachment_prefixes = json.loads(attachment_prefixes_serialized)
    for prefix in attachment_prefixes:
        try:
            file_name = prefix.split("/")[-1]
            file_name = f"/tmp/{file_name}"
            with open(file_name, "wb") as fp:
                s3.download_fileobj(MAIL_BUCKET, prefix, fp)
        except Exception as e:
            logging.error(f"{repr(e)}")
            raise e

        key_map, value_map, block_map = get_kv_map(file_name)

        # Get Key Value relationship
        kvs = get_kv_relationship(key_map, value_map, block_map)
        o = marshal_response(kvs)
        logging.info(f"{file_name}: {o}")
