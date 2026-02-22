def lambda_handler(event, context):
    # Minimal no-op handler used by CDK asset staging.
    return {
        "statusCode": 200,
        "body": "ok"
    }
