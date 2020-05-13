#!/usr/bin/env python

import os
import datetime
import sys
import re
import json
import boto3

MAIL_BUCKET = os.getenv("mail_bucket_name", "")
MAIL_BUCKET_REGION = os.getenv("mail_bucket_region", os.environ["AWS_DEFAULT_REGION"])

def get_kv_map(file_name):

    with open(file_name, 'rb') as fp:
        img_test = fp.read()
        bytes_test = bytearray(img_test)
        print('Image loaded', file_name)

        # process using image bytes
        client = boto3.client('textract')
        response = client.analyze_document(Document={'Bytes': bytes_test}, FeatureTypes=['FORMS'])

        # Get the text blocks
        blocks=response['Blocks']
        

        # get key and value maps
        key_map = {}
        value_map = {}
        block_map = {}
        for block in blocks:
            block_id = block['Id'].strip()
            block_map[block_id] = block
            if block['BlockType'] == "KEY_VALUE_SET":
                if 'KEY' in block['EntityTypes']:
                    key_map[block_id] = block
                else:
                    value_map[block_id] = block

        return key_map, value_map, block_map


def get_kv_relationship(key_map, value_map, block_map):
    kvs = {}
    for block_id, key_block in key_map.items():
        value_block = find_value_block(key_block, value_map)
        key = get_text(key_block, block_map)
        val = get_text(value_block, block_map)
        kvs[key] = val
    return kvs


def find_value_block(key_block, value_map):
    for relationship in key_block['Relationships']:
        if relationship['Type'] == 'VALUE':
            for value_id in relationship['Ids']:
                value_block = value_map[value_id]
    return value_block


def get_text(result, blocks_map):
    text = ''
    if 'Relationships' in result:
        for relationship in result['Relationships']:
            if relationship['Type'] == 'CHILD':
                for child_id in relationship['Ids']:
                    word = blocks_map[child_id]
                    if word['BlockType'] == 'WORD':
                        text += word['Text'] + ' '
                    if word['BlockType'] == 'SELECTION_ELEMENT':
                        if word['SelectionStatus'] == 'SELECTED':
                            text += 'X '    

                                
    return text


def marshal_response(kvs):
    ret = {}
    ret['Description'] = search_value(kvs, 'description').strip()
    ret['Vin'] = search_value(kvs, 'vin').strip()
    ret['Vehicle'] = search_value(kvs, 'vehicle').strip()
    ret['Odometer'] = re.findall(r"[\d]{1,7}", search_value(kvs, 'odometer'))[0].strip()
    ret['Date'] = search_value(kvs, 'invoiced').strip()
    ret['Amount'] = search_value(kvs, r'(?:^|(?<= ))(american|discover|visa|mastercard)(?:(?= )|$)').strip()
    ret['Tax'] = search_value(kvs, '5.3%').strip()

    return ret


def search_value(kvs, search_key):
    for key, value in kvs.items():
        if re.search(search_key, key, re.IGNORECASE):
            return value

def handler(event, context):
    print(event)
    s3 = boto3.client('s3', region_name=MAIL_BUCKET_REGION)

    attachment_prefixes_serialized = event['Records'][0]['Sns']['MessageAttributes']['attachments']['Value']
    attachment_prefixes = json.loads(attachment_prefixes_serialized)
    for prefix in attachment_prefixes:
        try:
            file_name = prefix.split('/')[-1]
            file_name = f"/tmp/{file_name}"
            with open(file_name, 'wb') as fp:
                s3.download_fileobj(MAIL_BUCKET, prefix, fp)
        except Exception as e:
            print(f"{repr(e)}")
            raise e

        key_map, value_map, block_map = get_kv_map(file_name)

        # Get Key Value relationship
        kvs = get_kv_relationship(key_map, value_map, block_map)
        o = marshal_response(kvs)
        print(f"{file_name}: {o}")
