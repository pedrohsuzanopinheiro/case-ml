"""
Local integration tests for the Lambda handler.
Uses moto to mock DynamoDB — no AWS credentials needed.
Run via Docker: see scripts/test_local.sh
"""
import json
import os

os.environ["DYNAMODB_TABLE"] = "test-sobreviventes"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "test"
os.environ["AWS_SECRET_ACCESS_KEY"] = "test"

import boto3
from moto import mock_aws

# Create DynamoDB table before importing handler (which loads model at module level)
@mock_aws
def run_tests():
    # Setup table
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="test-sobreviventes",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    import importlib
    import handler as h
    importlib.reload(h)  # re-init with mocked DynamoDB

    passenger = {
        "Age": 29, "Parch": 0, "SibSp": 1,
        "Fare": 26.5, "Pclass": 1, "Sex": "female", "Embarked": "S"
    }

    print("\n=== POST /sobreviventes ===")
    event = {
        "httpMethod": "POST",
        "resource": "/sobreviventes",
        "body": json.dumps(passenger),
        "pathParameters": None,
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 201, f"Expected 201, got {resp['statusCode']}: {resp['body']}"
    body = json.loads(resp["body"])
    assert "id" in body
    assert "survival_probability" in body
    item_id = body["id"]
    prob = body["survival_probability"]
    print(f"  OK — id={item_id}, survival_probability={prob}")

    print("\n=== GET /sobreviventes ===")
    event = {"httpMethod": "GET", "resource": "/sobreviventes", "pathParameters": None, "queryStringParameters": None}
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 200
    body_list = json.loads(resp["body"])
    assert "items" in body_list
    assert "count" in body_list
    assert body_list["count"] == 1
    assert len(body_list["items"]) == 1
    print(f"  OK — {body_list['count']} item(s) returned")

    print("\n=== GET /sobreviventes/{id} ===")
    event = {
        "httpMethod": "GET",
        "resource": "/sobreviventes/{id}",
        "pathParameters": {"id": item_id},
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 200
    item = json.loads(resp["body"])
    assert item["id"] == item_id
    print(f"  OK — item found: sex={item['sex']}, survival_probability={item['survival_probability']}")

    print("\n=== GET /sobreviventes/{id} — 404 ===")
    event["pathParameters"] = {"id": "nonexistent-id"}
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 404
    print("  OK — 404 returned for unknown id")

    print("\n=== DELETE /sobreviventes/{id} ===")
    event = {
        "httpMethod": "DELETE",
        "resource": "/sobreviventes/{id}",
        "pathParameters": {"id": item_id},
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 204
    print("  OK — 204 returned")

    print("\n=== DELETE /sobreviventes/{id} — 404 after deletion ===")
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 404
    print("  OK — 404 on second delete")

    print("\n=== GET after DELETE — list empty ===")
    event = {"httpMethod": "GET", "resource": "/sobreviventes", "pathParameters": None, "queryStringParameters": None}
    resp = h.lambda_handler(event, None)
    body_empty = json.loads(resp["body"])
    assert body_empty["count"] == 0
    assert len(body_empty["items"]) == 0
    print(f"  OK — 0 items after deletion")

    print("\n=== POST — missing fields ===")
    event = {
        "httpMethod": "POST",
        "resource": "/sobreviventes",
        "body": json.dumps({"Age": 29}),
        "pathParameters": None,
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 400
    print("  OK — 400 on missing fields")

    print("\n=== POST — male passenger from Southampton ===")
    passenger2 = {
        "Age": 45, "Parch": 0, "SibSp": 0,
        "Fare": 7.25, "Pclass": 3, "Sex": "male", "Embarked": "S"
    }
    event = {
        "httpMethod": "POST",
        "resource": "/sobreviventes",
        "body": json.dumps(passenger2),
        "pathParameters": None,
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 201
    body2 = json.loads(resp["body"])
    print(f"  OK — survival_probability={body2['survival_probability']} (expected low for 3rd-class male)")

    print("\n=== POST with id — update existing record ===")
    # First create a record
    passenger3 = {
        "Age": 22, "Parch": 1, "SibSp": 0,
        "Fare": 50.0, "Pclass": 2, "Sex": "female", "Embarked": "C"
    }
    event = {
        "httpMethod": "POST",
        "resource": "/sobreviventes",
        "body": json.dumps(passenger3),
        "pathParameters": None,
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 201
    created = json.loads(resp["body"])
    created_id = created["id"]
    original_prob = created["survival_probability"]
    print(f"  Created id={created_id}, prob={original_prob}")

    # Now update it with different data
    passenger3_updated = {
        "id": created_id,
        "Age": 55, "Parch": 0, "SibSp": 0,
        "Fare": 7.25, "Pclass": 3, "Sex": "male", "Embarked": "S"
    }
    event = {
        "httpMethod": "POST",
        "resource": "/sobreviventes",
        "body": json.dumps(passenger3_updated),
        "pathParameters": None,
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 200, f"Expected 200, got {resp['statusCode']}: {resp['body']}"
    updated = json.loads(resp["body"])
    assert updated["id"] == created_id
    print(f"  Updated id={updated['id']}, new_prob={updated['survival_probability']}")

    # Verify the record was actually updated in DynamoDB
    event = {
        "httpMethod": "GET",
        "resource": "/sobreviventes/{id}",
        "pathParameters": {"id": created_id},
    }
    resp = h.lambda_handler(event, None)
    item = json.loads(resp["body"])
    assert item["sex"] == "male", f"Expected sex=male after update, got {item['sex']}"
    assert item["pclass"] == 3, f"Expected pclass=3 after update, got {item['pclass']}"
    assert "updated_at" in item, "Expected updated_at field after update"
    print(f"  Verified: sex={item['sex']}, pclass={item['pclass']}, updated_at={item['updated_at']}")

    print("\n=== POST with id — nonexistent id returns 404 ===")
    passenger_bad_id = {
        "id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
        "Age": 30, "Parch": 0, "SibSp": 0,
        "Fare": 10.0, "Pclass": 2, "Sex": "male", "Embarked": "Q"
    }
    event = {
        "httpMethod": "POST",
        "resource": "/sobreviventes",
        "body": json.dumps(passenger_bad_id),
        "pathParameters": None,
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 404, f"Expected 404, got {resp['statusCode']}"
    print("  OK — 404 for nonexistent id")

    print("\n=== POST with id — invalid UUID returns 400 ===")
    passenger_invalid_id = {
        "id": "not-a-uuid",
        "Age": 30, "Parch": 0, "SibSp": 0,
        "Fare": 10.0, "Pclass": 2, "Sex": "male", "Embarked": "Q"
    }
    event = {
        "httpMethod": "POST",
        "resource": "/sobreviventes",
        "body": json.dumps(passenger_invalid_id),
        "pathParameters": None,
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 400, f"Expected 400, got {resp['statusCode']}"
    print("  OK — 400 for invalid UUID")

    print("\n=== GET /sobreviventes — pagination with limit ===")
    # At this point we have 2 items (passenger2 + passenger3_updated). Insert a 3rd.
    passenger4 = {
        "Age": 10, "Parch": 2, "SibSp": 1,
        "Fare": 30.0, "Pclass": 1, "Sex": "female", "Embarked": "Q"
    }
    event = {
        "httpMethod": "POST",
        "resource": "/sobreviventes",
        "body": json.dumps(passenger4),
        "pathParameters": None,
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 201

    # Fetch with limit=1
    event = {
        "httpMethod": "GET",
        "resource": "/sobreviventes",
        "pathParameters": None,
        "queryStringParameters": {"limit": "1"},
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 200
    page1 = json.loads(resp["body"])
    assert page1["count"] == 1
    assert len(page1["items"]) == 1
    assert "last_key" in page1, "Expected last_key when there are more items"
    print(f"  Page 1: count={page1['count']}, last_key={page1['last_key']}")

    # Fetch next page using last_key
    event["queryStringParameters"] = {"limit": "1", "last_key": page1["last_key"]}
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 200
    page2 = json.loads(resp["body"])
    assert page2["count"] == 1
    assert page2["items"][0]["id"] != page1["items"][0]["id"]
    print(f"  Page 2: count={page2['count']}, last_key={page2.get('last_key', 'N/A')}")

    # Fetch all at once (default limit=20 > 3 items)
    event = {
        "httpMethod": "GET",
        "resource": "/sobreviventes",
        "pathParameters": None,
        "queryStringParameters": None,
    }
    resp = h.lambda_handler(event, None)
    all_items = json.loads(resp["body"])
    assert all_items["count"] == 3
    assert "last_key" not in all_items, "No last_key expected when all items fit in one page"
    print(f"  All at once: count={all_items['count']}, no last_key")

    print("\n=== GET /sobreviventes — invalid limit ===")
    event = {
        "httpMethod": "GET",
        "resource": "/sobreviventes",
        "pathParameters": None,
        "queryStringParameters": {"limit": "0"},
    }
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 400
    print("  OK — 400 for limit=0")

    event["queryStringParameters"] = {"limit": "abc"}
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 400
    print("  OK — 400 for limit=abc")

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    run_tests()
