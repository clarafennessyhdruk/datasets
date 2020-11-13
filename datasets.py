#!/usr/bin/env python
# usage: datasets.py
__author__ = "Susheel Varma"
__copyright__ = "Copyright (c) 2019-2020 Susheel Varma All Rights Reserved."
__email__ = "susheel.varma@hdruk.ac.uk"
__license__ = "Apache 2"

import sys
import copy
import csv
import json
import urllib
import codecs
import uuid
import itertools
import requests
from pprint import pprint
from migrate_v1_to_v2 import map_data

API_BASE_URL="https://metadata-catalogue.org/hdruk/api"
DATA_MODELS = API_BASE_URL + "/dataModels"
DATA_MODEL_ID = API_BASE_URL + "/facets/{MODEL_ID}/profile/uk.ac.hdrukgateway/HdrUkProfilePluginService"
DATA_MODEL_METADATA = API_BASE_URL + "/facets/{MODEL_ID}/metadata?all=true"
DATA_MODEL_CLASSES = DATA_MODELS + "/{MODEL_ID}/dataClasses"
DATA_MODEL_CLASSES_ELEMENTS = DATA_MODEL_CLASSES + "/{CLASS_ID}/dataElements?all=true"
DATA_MODEL_SEMANTIC_LINKS = API_BASE_URL + "/catalogueItems/{MODEL_ID}/semanticLinks"
DATA_MODEL_PIDS = "https://api.www.healthdatagateway.org/api/v1/datasets/pidList"

def request_url(URL):
  """HTTP GET request and load into data_model"""
  print(URL)
  r = requests.get(URL)
  if r.status_code == requests.codes.unauthorized:
    return {}
  elif r.status_code == requests.codes.not_found:
    return {}
  elif r.status_code != requests.codes.ok:
    r.raise_for_status()
  return json.loads(r.text)

def read_json(filename):
  with open(filename, 'r') as file:
    return json.load(file)

def export_csv(data, filename, header=None):
  if header is None:
    header = ['id', 'name', 'publisher', 'description', 'author', 'metadata_version']
  with open(filename, 'w') as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=header)
    writer.writeheader()
    writer.writerows(data)

def export_json(data, filename, indent=2):
  with open(filename, 'w') as jsonfile:
    json.dump(data, jsonfile, indent=indent)

def get_data_elements(data_model_id, data_class_id):
  print("Processing Data Elements...")
  data = []
  URL = DATA_MODEL_CLASSES_ELEMENTS.format(MODEL_ID=data_model_id, CLASS_ID=data_class_id)
  de_row = request_url(URL)
  data_element_count = int(de_row.get('count', 0))
  if data_element_count > 0:
    for d in de_row['items']:
      print("Processing Data Element: ", d['id'], " : ", d['label'])
      del d['id']
      del d['domainType']
      d['name'] = d.pop('label', None)
      del d['breadcrumbs']
      del d['dataModel']
      del d['dataClass']
      d['dataType'] = d['dataType']['label']
      data.append(d)
  return data

def get_data_classes(data_model_id):
  print("Processing Data Classes...")
  data = {}
  URL = DATA_MODEL_CLASSES.format(MODEL_ID=data_model_id)
  dm_row = request_url(URL)
  data_model_count = int(dm_row.get('count', 0))
  data['dataClassesCount'] = data_model_count
  data_classes = []
  if data_model_count > 0:
    for d in dm_row['items']:
      print("Processing Data Class: ", d['id'], " : ", d['label'])
      URL = DATA_MODEL_CLASSES.format(MODEL_ID=data_model_id) + "/{CLASS_ID}".format(CLASS_ID=d['id'])
      dc_row = request_url(URL)
      del dc_row['id']
      del dc_row['domainType']
      dc_row['name'] = dc_row.pop('label', None)
      del dc_row['breadcrumbs']
      del dc_row['dataModel']
      del dc_row['editable']
      del dc_row['lastUpdated']
      
      # Collecting DataElements
      data_elements = get_data_elements(data_model_id, d['id'])
      dc_row['dataElementsCount'] = len(data_elements)
      dc_row['dataElements'] = data_elements
      data_classes.append(dc_row)
  data['dataClasses'] = data_classes
  return data

def get_semantic_links(data_model_id):
  print("Processing Semantic Links...")
  data = {}
  URL = DATA_MODEL_SEMANTIC_LINKS.format(MODEL_ID=data_model_id)
  ret = request_url(URL)
  if ret['count'] > 0:
    for links in ret['items']:
      src_ver = links['source']['documentationVersion']
      src_id = links['source']['id']
      data[src_ver] = src_id

      tar_ver = links['target']['documentationVersion']
      tar_id = links['target']['id']
      data[tar_ver] = tar_id
  data['latest'] = data_model_id
  return { 'revisions': data }

def fix_dates(revisions):
  print("Fixing Dates...")
  from datetime import datetime
  data = {}
  last_updated = []
  date_finalised = []
  for version, id in revisions.items():
    URL = DATA_MODELS + "/" + id
    ret = request_url(URL)
    if ret.get("lastUpdated", None) is not None:
      try:
        lu = datetime.strptime(ret["lastUpdated"], "%Y-%m-%dT%H:%M:%S.%fZ")
      except ValueError:
        lu = datetime.strptime(ret["lastUpdated"], "%Y-%m-%dT%H:%M:%SZ")
    else:
      lu = None
    if ret.get("dateFinalised", None) is not None:
      try:
        du = datetime.strptime(ret["dateFinalised"], "%Y-%m-%dT%H:%M:%S.%fZ")
      except ValueError:
        du = datetime.strptime(ret["dateFinalised"], "%Y-%m-%dT%H:%M:%SZ")
    else:
      du = lu
    if lu is not None: last_updated.append(lu)
    if du is not None: date_finalised.append(du)
  if len(last_updated) > 0:
    data['modified'] = max(last_updated).strftime("%Y-%m-%dT%H:%M:%SZ")
  else:
    data['modified'] = None
  if len(date_finalised) > 0:
    data['issued'] = min(date_finalised).strftime("%Y-%m-%dT%H:%M:%SZ")
  else:
    data['issued'] = None
  return data

def process_data_models(data_models_list):
  print("Processing Data Models...")
  headers = []
  data = {}
  data['count'] = data_models_list['count']
  data_models = []
  data_models_v2 = []
  
  # Collect PIDs for Datasets
  pid_list = request_url(DATA_MODEL_PIDS)
  # pid_list = read_json("pids.json")
  
  for d in data_models_list['items']:
    print("Processing Data Model: ", d['id'])
    row = {}
    row["@schema"] = {
        "type": "Dataset",
        "version": "1.1.7",
        "url": "https://raw.githubusercontent.com/HDRUK/schemata/develop/schema/dataset/1.1.7/dataset.schema.json"
    }

    # Get PID for Dataset
    for p in pid_list['data']:
      if d['id'] in p['datasetIds']:
        row['pid'] = p['pid']
    
    # Collect Data Model
    URL = DATA_MODELS + "/{ID}".format(ID=d['id'])
    dm = request_url(URL)
    row.update(dm)
    row['version'] = row.pop('documentationVersion', None)
    
    # Collect HDR UK Profile information
    URL = DATA_MODEL_ID.format(MODEL_ID=d['id'])
    dm = request_url(URL)
    row.update(dm)

    row_v2 = {
      "@schema": {
        "type": "Dataset",
        "version": "2.0.0",
        "url": "https://raw.githubusercontent.com/HDRUK/schemata/develop/schema/dataset/latest/dataset.schema.json"
      },
      "pid": row.get('pid', None),
      "id": row['id'],
      "identifier": "https://web.www.healthdatagateway.org/dataset/" + dm['id'],
      "version": row.get("version", None),
      "lastUpdated": row.get('lastUpdated', None),
      "dateFinalised": row.get('dateFinalised', None),
      "summary": {
        "title": row.get('label', None)
      },
      "documentation": {
        "description": row.get('description', None)
      }
    }

    # Collect SemanticLinks
    semantic_links = get_semantic_links(d['id'])
    row.update(semantic_links)
    row_v2.update(semantic_links)

    # Fix Dates
    dates = fix_dates(row['revisions'])
    row.update(dates)
    row_v2.update(dates)
    row.pop('lastUpdated', None)
    row.pop('dateFinalised', None)
    row_v2.pop('lastUpdated', None)
    row_v2.pop('dateFinalised', None)

    # Collect HDR UK V2 Metadata Profile information
    metadata_v2 = get_v2_metadata(row['id'])
    row_v2 = generate_nested_dict(row_v2, metadata_v2)

    # Collecting Data Classes
    data_classes = get_data_classes(d['id'])
    row.update(data_classes)
    row_v2.update({ "structuralMetadata": data_classes})

    data_models.append(row)
    if len(metadata_v2) > 0:
      data_models_v2.append(row_v2)
    
  data['dataModels'] = data_models
  data['dataModelsV2'] = data_models_v2
  data['count_v1'] = len(data_models)
  data['count_v2'] = len(data_models_v2)
  print("Retrieved ", data['count_v1'], "V1 records & ", data['count_v2'], " V2 records.")
  return data

def format_csv_tables(data):
  tables = {
    'dataModels': {'data': [], 'headers': []},
    'dataClasses': {'data': [], 'headers': []},
    'dataElements': {'data': [], 'headers': []},
  }
  for dm in data['dataModels']:
    for dc in dm['dataClasses']:
      for de in dc['dataElements']:
        de['dataTypeLabel'] = de['dataType']['label']
        de['dataType'] = de['dataType']['domainType']
        de['dataModel'] = dm['id']
        de['dataClass'] = dc['id']
        # Append dataElement to tables
        tables['dataElements']['data'].append(de)
        tables['dataElements']['headers'].extend(de.keys())
      # Add dataElement IDs to dataClass
      data_elements = [de['id'] for de in dc['dataElements']]
      dc['dataElements'] = ", ".join(data_elements)
      # Append dataClass to tables
      tables['dataClasses']['data'].append(dc)
      tables['dataClasses']['headers'].extend(dc.keys())
    # Add dataClasses to dataModel
    data_classes = [dc['id'] for dc in dm['dataClasses']]
    data['dataClasses'] = ", ".join(data_classes)
    tables['dataModels']['data'].append(dm)
    tables['dataModels']['headers'].extend(dm.keys())
  tables['dataModels']['headers'] = list(set(tables['dataModels']['headers']))
  tables['dataClasses']['headers'] = list(set(tables['dataClasses']['headers']))
  tables['dataElements']['headers'] = list(set(tables['dataElements']['headers']))
  print("Count: DM ", data['count'], len(data['dataModels']), len(tables['dataModels']['data']))
  print("Count: DC ", len(tables['dataClasses']['data']))
  print("Count: DE ", len(tables['dataElements']['data']))
  return tables

def migrate_v1_to_v2(data):
  new_data = []
  count = data['count']
  data = data['dataModels']
  for d in data:
    new_d = {}
    map_data(d, new_d)
    new_data.append(new_d)
  return {
    'count': len(new_data),
    'dataModels': new_data
  }

def lookup_pids(data):
  pid_list = request_url(DATA_MODEL_PIDS)
  for d in data['dataModels']:
    id = d['id']
    for p in pid_list['data']:
      if id in p['datasetIds']:
        d['pid'] = p['pid']
  return data


def generate_sitemap(data, filename):
  BASE_URL = "https://www.healthdatagateway.org/"
  DATASET_BASE_URL = "https://web.www.healthdatagateway.org/dataset/{}"
  PAGES = [
    "https://www.healthdatagateway.org/pages/about",
    "https://www.healthdatagateway.org/pages/community",
    "https://www.healthdatagateway.org/pages/cookie-notice",
    "https://www.healthdatagateway.org/covid-19",
    "https://www.healthdatagateway.org/pages/frequently-asked-questions",
    "https://www.healthdatagateway.org/pages/guidelines",
    "https://www.healthdatagateway.org/pages/key-terms-glossary",
    "https://www.healthdatagateway.org/pages/latest-news",
    "https://www.healthdatagateway.org/pages/metadata-quality"
  ]

  for d in data['dataModels']:
    id = d['id']
    PAGES.append(DATASET_BASE_URL.format(id))

  with codecs.open(filename, 'w', encoding='utf8') as f:
    f.write(BASE_URL + '\n')
    f.writelines('\n'.join(PAGES))

def nested_set(dic, keys, value):
  for key in keys[:-1]:
      dic = dic.setdefault(key, {})
  dic[keys[-1]] = value

def generate_nested_dict(metadata, data):
  for d in data:
    nested_set(metadata, d[0], d[1])
  return metadata

def get_v2_metadata(id):
  import ast
  print("Downloading V2 metadata...")
  URL = DATA_MODEL_METADATA.format(MODEL_ID=id)
  data = request_url(URL)
  metadata = []
  for md in data['items']:
    if md['value'].startswith("[") and md['value'].endswith("]"):
      md['value'] = ast.literal_eval(md['value'])
    if md['namespace'] == 'org.healthdatagateway':
      if md['key'] == "structuralMetadata":
        metadata.append(([md['key']], md['value']))
      else:
        key = str(md['key'].split('properties/')[1])
        keys = key.split("/")
        metadata.append((keys, md['value']))
  return metadata


def main():
  data_models_list = request_url(DATA_MODELS)

  data_v1 = process_data_models(data_models_list)
  data_v2 = copy.deepcopy(data_v1)

  del data_v1['dataModelsV2']
  del data_v1['count_v2']
  data_v1['count'] = data_v2.pop("count_v1")
  
  del data_v2['dataModels']
  data_v2['dataModels'] = data_v2.pop('dataModelsV2')
  data_v2['count'] = data_v2.pop("count_v2")

  export_json(data_v1, 'datasets.json')
  export_json(data_v2, 'datasets.v2.json')

  # # generate sitemap
  # generate_sitemap(data, 'sitemap.txt')
  
  # tables = format_csv_tables(data_v1)
  # export_csv(tables['dataModels']['data'], 'datasets.csv', tables['dataModels']['headers'])
  # export_csv(tables['dataClasses']['data'], 'dataclasses.csv', tables['dataClasses']['headers'])
  # export_csv(tables['dataElements']['data'], 'dataelements.csv', tables['dataElements']['headers'])



if __name__ == "__main__":
    main()
