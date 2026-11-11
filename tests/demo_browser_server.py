"""Isolated localhost-only browser fixture; never connects to a real AWS service."""
import os
import boto3
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.core.security import hash_password
from app.dynamo_demo_repository import DynamoDemoRepository
from app.routers import data_api_demo

assert os.environ.get('DEMO_BROWSER_FIXTURE') == '1'
db=boto3.resource('dynamodb',endpoint_url='http://127.0.0.1:8000',region_name='us-east-1',aws_access_key_id='local',aws_secret_access_key='local')
table=db.create_table(TableName='BrowserFixture',KeySchema=[{'AttributeName':'pk','KeyType':'HASH'},{'AttributeName':'sk','KeyType':'RANGE'}],AttributeDefinitions=[{'AttributeName':'pk','AttributeType':'S'},{'AttributeName':'sk','AttributeType':'S'}],BillingMode='PAY_PER_REQUEST')
table.wait_until_exists()
table.put_item(Item={'pk':'USER#1','sk':'PROFILE','id':1,'name':'Demo Admin','email':'admin@example.edu','password_hash':hash_password('Password1!'),'role':'admin'})
table.put_item(Item={'pk':'PLACE','sk':'001','id':1,'name':'Library','active':True,'kind':'building'})
table.put_item(Item={'pk':'DEMO#CONTACT','sk':'001','id':1,'name':'Demo medical team','kind':'medical','shift':'all','phone':'DEMO-001','active':True,'outcome':'accepted','delay_seconds':0})
repo=DynamoDemoRepository(table=table)
class Ledger:
    def __init__(self): self.items={}
    def claim(self,key): return {'state':'completed','alert_id':self.items[key]} if key in self.items else {'state':'claimed'}
    def complete(self,key,alert_id): self.items[key]=alert_id
ledger=Ledger()
app=FastAPI()
app.include_router(data_api_demo.router,prefix='/api/v1')
app.dependency_overrides[data_api_demo.get_repo]=lambda:repo
app.dependency_overrides[data_api_demo.ledger]=lambda:ledger
app.mount('/static',StaticFiles(directory='/var/task/frontend'),name='static')
@app.get('/')
def page(): return FileResponse('/var/task/frontend/medical.html')
