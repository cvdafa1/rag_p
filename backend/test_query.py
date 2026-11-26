import chromadb

client = chromadb.PersistentClient(path="./data/chroma_db")
collection = client.get_collection("enterprise_kb")

print(collection.count())

res = collection.get(
    ids=["3c15463b-6d87-4cb9-b581-d5a2a07b863c_C01", "3c15463b-6d87-4cb9-b581-d5a2a07b863c_C02"],
    limit=20,
    offset=0,
    include=["documents", "metadatas"]  # 不加 embeddings，太大
)

for _id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"]):
    print("=" * 60)
    print("id:", _id)
    print("metadata:", meta)
    print("document:", doc)

    

