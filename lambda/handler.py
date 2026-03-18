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


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value, version=4)
        return True
    except (ValueError, AttributeError):
        return False


def post_sobreviventes(event):
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    required = ["Age", "Parch", "SibSp", "Fare", "Pclass", "Sex", "Embarked"]
    missing = [f for f in required if f not in payload]
    if missing:
        return _response(400, {"error": f"Missing fields: {missing}"})

    provided_id = payload.get("id")
    if provided_id is not None:
        if not _is_valid_uuid(provided_id):
            return _response(400, {"error": "Field 'id' must be a valid UUID v4"})
        existing = TABLE.get_item(Key={"id": provided_id}).get("Item")
        if not existing:
            return _response(404, {"error": f"Survivor with id '{provided_id}' not found"})

    df = preprocess(payload)
    prob = float(MODEL.predict_proba(df)[:, 1][0])

    now = __import__("datetime").datetime.utcnow().isoformat() + "Z"

    if provided_id:
        item_id = provided_id
        TABLE.update_item(
            Key={"id": item_id},
            UpdateExpression="SET age=:age, parch=:parch, sibsp=:sibsp, fare=:fare, "
                             "pclass=:pclass, sex=:sex, embarked=:embarked, "
                             "survival_probability=:prob, updated_at=:upd",
            ExpressionAttributeValues={
                ":age": Decimal(str(round(payload["Age"], 6))) if payload["Age"] is not None else Decimal("0"),
                ":parch": int(payload["Parch"]),
                ":sibsp": int(payload["SibSp"]),
                ":fare": Decimal(str(round(payload["Fare"], 6))),
                ":pclass": int(payload["Pclass"]),
                ":sex": str(payload["Sex"]),
                ":embarked": str(payload["Embarked"]),
                ":prob": Decimal(str(round(prob, 6))),
                ":upd": now,
            },
        )
        return _response(200, {"id": item_id, "survival_probability": round(prob, 6)})

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
        "created_at": now,
    }
    TABLE.put_item(Item=item)

    return _response(201, {"id": item_id, "survival_probability": round(prob, 6)})


DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


def get_sobreviventes(event):
    params = event.get("queryStringParameters") or {}

    try:
        limit = int(params.get("limit", DEFAULT_PAGE_LIMIT))
        if limit < 1 or limit > MAX_PAGE_LIMIT:
            raise ValueError
    except (ValueError, TypeError):
        return _response(400, {"error": f"'limit' must be an integer between 1 and {MAX_PAGE_LIMIT}"})

    kwargs = {"Limit": limit}
    last_key_param = params.get("last_key")
    if last_key_param:
        kwargs["ExclusiveStartKey"] = {"id": last_key_param}

    result = TABLE.scan(**kwargs)
    items = [_item_to_dict(i) for i in result.get("Items", [])]

    body = {"items": items, "count": len(items)}
    next_key = result.get("LastEvaluatedKey")
    if next_key:
        body["last_key"] = next_key["id"]

    return _response(200, body)


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
