from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017")
db = client["electiondbaccounting"]
print("otps count:", db.otps.count_documents({}))
for doc in db.otps.find({}).limit(3):
    print(doc)
print("---orgs---")
for o in db.organizations.find({}):
    print(o.get("slug"), str(o["_id"]))