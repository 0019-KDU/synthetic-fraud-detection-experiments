"""
Payment API Endpoint - Submit transactions and get fraud detection results
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

import requests
from confluent_kafka import Producer, Consumer
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from jsonschema import validate, ValidationError, FormatChecker

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(module)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(dotenv_path="/app/.env")

app = Flask(__name__)

# Kafka configuration
bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
kafka_username = os.getenv("KAFKA_USERNAME")
kafka_password = os.getenv("KAFKA_PASSWORD")
transactions_topic = os.getenv("KAFKA_TOPIC", "transactions")
predictions_topic = "fraud_predictions"

# Producer configuration
producer_config = {
    "bootstrap.servers": bootstrap_servers,
    "client.id": "payment-api",
}

if kafka_username and kafka_password:
    producer_config.update({
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "PLAIN",
        "sasl.username": kafka_username,
        "sasl.password": kafka_password,
    })

producer = Producer(producer_config)

# Consumer configuration for reading predictions
consumer_config = {
    "bootstrap.servers": bootstrap_servers,
    "group.id": "payment-api-consumer",
    "auto.offset.reset": "latest",
    "enable.auto.commit": False,
}

if kafka_username and kafka_password:
    consumer_config.update({
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "PLAIN",
        "sasl.username": kafka_username,
        "sasl.password": kafka_password,
    })

consumer = Consumer(consumer_config)
consumer.subscribe([predictions_topic])

# Transaction schema for validation
PAYMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "transaction_id": {"type": "string"},
        "user_id": {"type": "integer", "minimum": 1000, "maximum": 9999},
        "amount": {"type": "number", "minimum": 0.01},
        "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
        "merchant": {"type": "string"},
        "location": {"type": "string", "pattern": "^[A-Z]{2}$"},
    },
    "required": ["transaction_id", "user_id", "amount", "merchant"]
}


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "payment-api"}), 200


@app.route('/payment', methods=['POST'])
def process_payment():
    """
    Process payment transaction and return fraud detection result
    
    Expected JSON body:
    {
        "transaction_id": "3895742",
        "user_id": 5432,
        "amount": 1250.50,
        "currency": "USD",
        "merchant": "Amazon",
        "location": "US"
    }
    
    Returns:
    {
        "status": "success",
        "transaction_id": "3895742",
        "result": "legitimate" or "fraud",
        "fraud_probability": 0.15,
        "message": "Transaction approved" or "Transaction blocked - suspected fraud"
    }
    """
    try:
        # Parse request JSON
        payment_data = request.get_json()
        
        if not payment_data:
            return jsonify({
                "status": "error",
                "message": "Invalid JSON payload"
            }), 400
        
        # Validate payment data
        try:
            validate(
                instance=payment_data,
                schema=PAYMENT_SCHEMA,
                format_checker=FormatChecker()
            )
        except ValidationError as e:
            return jsonify({
                "status": "error",
                "message": f"Validation error: {e.message}"
            }), 400
        
        # Add timestamp if not provided
        if "timestamp" not in payment_data:
            payment_data["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        # Set default values
        payment_data.setdefault("currency", "USD")
        payment_data.setdefault("location", "US")
        payment_data.setdefault("is_fraud", 0)  # Default to legitimate
        
        transaction_id = payment_data["transaction_id"]
        
        logger.info(f"Processing payment: {transaction_id}")
        
        # Send transaction to Kafka
        producer.produce(
            transactions_topic,
            key=transaction_id,
            value=json.dumps(payment_data)
        )
        producer.flush(timeout=5)
        
        logger.info(f"Transaction sent to Kafka: {transaction_id}")
        
        # Wait for prediction result (timeout 10 seconds)
        prediction_result = wait_for_prediction(transaction_id, timeout=10)
        
        if prediction_result:
            is_fraud = prediction_result.get("prediction", 0)
            fraud_probability = prediction_result.get("fraud_probability", 0.0)
            
            response = {
                "status": "success",
                "transaction_id": transaction_id,
                "result": "fraud" if is_fraud == 1 else "legitimate",
                "fraud_probability": round(fraud_probability, 4),
                "risk_level": get_risk_level(fraud_probability),
                "message": "Transaction blocked - suspected fraud" if is_fraud == 1 else "Transaction approved",
                "details": {
                    "user_id": payment_data["user_id"],
                    "amount": payment_data["amount"],
                    "currency": payment_data["currency"],
                    "merchant": payment_data["merchant"],
                    "location": payment_data["location"]
                }
            }
            
            logger.info(f"Payment processed: {transaction_id} - Result: {response['result']}")
            return jsonify(response), 200
        else:
            # Prediction timeout - return pending status
            return jsonify({
                "status": "pending",
                "transaction_id": transaction_id,
                "message": "Transaction submitted, fraud detection in progress",
                "note": "Check /payment/{transaction_id} for results"
            }), 202
    
    except Exception as e:
        logger.error(f"Error processing payment: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Internal server error: {str(e)}"
        }), 500


def wait_for_prediction(transaction_id, timeout=10):
    """
    Wait for prediction result from fraud_predictions topic
    
    Args:
        transaction_id: Transaction ID to wait for
        timeout: Maximum wait time in seconds
    
    Returns:
        Prediction result dict or None if timeout
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        msg = consumer.poll(timeout=1.0)
        
        if msg is None:
            continue
        
        if msg.error():
            logger.error(f"Consumer error: {msg.error()}")
            continue
        
        try:
            prediction = json.loads(msg.value().decode('utf-8'))
            
            if prediction.get("transaction_id") == transaction_id:
                logger.info(f"Prediction received for {transaction_id}")
                return prediction
        
        except Exception as e:
            logger.error(f"Error parsing prediction: {str(e)}")
    
    logger.warning(f"Prediction timeout for transaction {transaction_id}")
    return None


def get_risk_level(fraud_probability):
    """Categorize risk level based on fraud probability"""
    if fraud_probability >= 0.7:
        return "HIGH"
    elif fraud_probability >= 0.4:
        return "MEDIUM"
    else:
        return "LOW"


if __name__ == '__main__':
    logger.info("🚀 Starting Payment API on port 5001...")
    app.run(host='0.0.0.0', port=5001, debug=False)
