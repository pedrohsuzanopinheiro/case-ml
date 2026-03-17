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
    event = {"httpMethod": "GET", "resource": "/sobreviventes", "pathParameters": None}
    resp = h.lambda_handler(event, None)
    assert resp["statusCode"] == 200
    items = json.loads(resp["body"])
    assert len(items) == 1
    print(f"  OK — {len(items)} item(s) returned")

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
    event = {"httpMethod": "GET", "resource": "/sobreviventes", "pathParameters": None}
    resp = h.lambda_handler(event, None)
    items = json.loads(resp["body"])
    assert len(items) == 0
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

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    run_tests()
