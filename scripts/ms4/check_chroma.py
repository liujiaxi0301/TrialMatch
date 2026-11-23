"""Verify the API container can query Chroma after its container is recreated."""

import os
import sys

import chromadb


client = chromadb.HttpClient(
    host=os.environ["CHROMADB_HOST"], port=int(os.environ["CHROMADB_PORT"])
)
name = "trialmatch-ms4-persistence-check"
if sys.argv[1] == "write":
    collection = client.get_or_create_collection(name, embedding_function=None)
    collection.upsert(
        ids=["diabetes", "asthma"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        documents=["type 2 diabetes trial", "asthma trial"],
    )
    print("Wrote the test collection through the API-to-Chroma network.")
elif sys.argv[1] == "read":
    collection = client.get_collection(name, embedding_function=None)
    answer = collection.query(query_embeddings=[[1.0, 0.0]], n_results=1)
    assert answer["ids"] == [["diabetes"]], answer
    assert answer["documents"] == [["type 2 diabetes trial"]], answer
    client.delete_collection(name)
    print("PASS: vectors survived container recreation; only the test collection was removed.")
else:
    raise SystemExit("Expected write or read")
