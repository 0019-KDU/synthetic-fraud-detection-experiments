import json
import logging
import os
import threading
from collections import deque
from datetime import datetime

import yaml
from confluent_kafka import Consumer, KafkaError
from dotenv import load_dotenv
from flask import Flask, render_template
from flask_socketio import SocketIO, emit

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(module)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(dotenv_path="../.env")

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'fraud-detection-dashboard-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Load configuration
with open('../config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Store recent transactions (last 100)
recent_transactions = deque(maxlen=100)
fraud_stats = {
    'total_transactions': 0,
    'fraud_detected': 0,
    'legitimate': 0,
    'fraud_rate': 0.0,
    'total_amount': 0.0,
    'fraud_amount': 0.0
}

# Kafka consumer setup
bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
kafka_username = os.getenv("KAFKA_USERNAME")
kafka_password = os.getenv("KAFKA_PASSWORD")
topic = config['kafka']['output_topic']  # fraud_predictions

consumer_config = {
    "bootstrap.servers": bootstrap_servers,
    "group.id": "fraud-dashboard",
    "auto.offset.reset": "latest",
    "enable.auto.commit": True,
}

if kafka_username and kafka_password:
    consumer_config.update({
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "PLAIN",
        "sasl.username": kafka_username,
        "sasl.password": kafka_password,
    })
else:
    consumer_config["security.protocol"] = "PLAINTEXT"

consumer = Consumer(consumer_config)
consumer.subscribe([topic])


def consume_kafka_messages():
    """Background thread to consume Kafka messages"""
    logger.info(f"🚀 Dashboard Kafka consumer started for topic: {topic}")
    
    while True:
        try:
            msg = consumer.poll(timeout=1.0)
            
            if msg is None:
                continue
            
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error(f"Consumer error: {msg.error()}")
                continue
            
            # Parse message
            transaction = json.loads(msg.value().decode('utf-8'))
            
            # Add timestamp if not present
            if 'dashboard_timestamp' not in transaction:
                transaction['dashboard_timestamp'] = datetime.now().isoformat()
            
            # Update statistics
            fraud_stats['total_transactions'] += 1
            amount = float(transaction.get('amount', 0))
            fraud_stats['total_amount'] += amount
            
            if transaction.get('prediction') == 1:
                fraud_stats['fraud_detected'] += 1
                fraud_stats['fraud_amount'] += amount
            else:
                fraud_stats['legitimate'] += 1
            
            # Calculate fraud rate
            if fraud_stats['total_transactions'] > 0:
                fraud_stats['fraud_rate'] = (
                    fraud_stats['fraud_detected'] / fraud_stats['total_transactions']
                ) * 100
            
            # Add to recent transactions
            recent_transactions.appendleft(transaction)
            
            # Emit to all connected clients
            socketio.emit('new_transaction', {
                'transaction': transaction,
                'stats': fraud_stats.copy()
            })
            
            logger.info(f"📊 Transaction processed: {transaction.get('transaction_id')} "
                       f"(Fraud: {transaction.get('prediction') == 1})")
        
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")


@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info("📱 Client connected to dashboard")
    
    # Send current stats and recent transactions to new client
    emit('initial_data', {
        'transactions': list(recent_transactions),
        'stats': fraud_stats.copy()
    })


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info("📴 Client disconnected from dashboard")


if __name__ == '__main__':
    # Start Kafka consumer in background thread
    kafka_thread = threading.Thread(target=consume_kafka_messages, daemon=True)
    kafka_thread.start()
    
    # Start Flask-SocketIO server
    logger.info("🌐 Starting Fraud Detection Dashboard on port 5000...")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
