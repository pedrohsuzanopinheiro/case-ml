import json
import os
import pickle
import uuid
from decimal import Decimal

import boto3

from preprocessing import preprocess

MODEL = pickle.load(open("model.pkl", "rb"))

dynamodb = boto3.resource("dynamodb")
TABLE = dynamodb.Table(os.environ["DYNAMODB_TABLE"])


def _response(status_code: int, body=None):
    resp = {"statusCode": status_code, "headers": {"Content-Type": "application/json"}}
    if body is not None:
        resp["body"] = json.dumps(body, default=str)
    return resp


def _item_to_dict(item: dict) -> dict:
    out = {}
    for k, v in item.items():
        out[k] = float(v) if isinstance(v, Decimal) else v
    return out


def post_sobreviventes(event):
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    required = ["Age", "Parch", "SibSp", "Fare", "Pclass", "Sex", "Embarked"]
    missing = [f for f in required if f not in payload]
    if missing:
        return _response(400, {"error": f"Missing fields: {missing}"})

    df = preprocess(payload)
    prob = float(MODEL.predict_proba(df)[:, 1][0])

    item_id = str(uuid.uuid4())
    item = {
        "id": item_id,
        "age": Decimal(str(round(payload["Age"], 6))) if payload["Age"] is not None else Decimal("0"),
        "parch": int(payload["Parch"]),
        "sibsp": int(payload["SibSp"]),
        "fare": Decimal(str(round(payload["Fare"], 6))),
        "pclass": int(payload["Pclass"]),
        "sex": str(payload["Sex"]),
        "embarked": str(payload["Embarked"]),
        "survival_probability": Decimal(str(round(prob, 6))),
        "created_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }
    TABLE.put_item(Item=item)

    return _response(201, {"id": item_id, "survival_probability": round(prob, 6)})


def get_sobreviventes(_event):
    items = []
    kwargs = {}
    while True:
        result = TABLE.scan(**kwargs)
        items.extend(result.get("Items", []))
        last_key = result.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key

    return _response(200, [_item_to_dict(i) for i in items])


def get_sobrevivente_by_id(event):
    item_id = event["pathParameters"]["id"]
    result = TABLE.get_item(Key={"id": item_id})
    item = result.get("Item")
    if not item:
        return _response(404, {"error": "Not found"})
    return _response(200, _item_to_dict(item))


def delete_sobrevivente(event):
    item_id = event["pathParameters"]["id"]
    try:
        TABLE.delete_item(
            Key={"id": item_id},
            ConditionExpression="attribute_exists(id)",
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return _response(404, {"error": "Not found"})
    return _response(204)


ROUTES = {
    ("POST", "/sobreviventes"): post_sobreviventes,
    ("GET", "/sobreviventes"): get_sobreviventes,
    ("GET", "/sobreviventes/{id}"): get_sobrevivente_by_id,
    ("DELETE", "/sobreviventes/{id}"): delete_sobrevivente,
}


def lambda_handler(event, _context):
    method = event.get("httpMethod", "")
    resource = event.get("resource", "")
    handler_fn = ROUTES.get((method, resource))
    if handler_fn is None:
        return _response(404, {"error": "Route not found"})
    return handler_fn(event)
