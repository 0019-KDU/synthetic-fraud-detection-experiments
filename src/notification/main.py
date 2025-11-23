import json
import logging
import os
import signal
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any

import yaml
from confluent_kafka import Consumer, KafkaError
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(module)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(dotenv_path="/app/.env")


class FraudNotificationService:
    def __init__(self):
        # Load configuration
        with open('/app/config.yaml', 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Kafka configuration
        self.bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self.kafka_username = os.getenv("KAFKA_USERNAME")
        self.kafka_password = os.getenv("KAFKA_PASSWORD")
        self.topic = self.config['kafka']['output_topic']  # fraud_predictions
        
        # MailDev SMTP configuration
        self.smtp_host = os.getenv("MAILDEV_HOST", "maildev")
        self.smtp_port = int(os.getenv("MAILDEV_SMTP_PORT", "1025"))
        self.from_email = os.getenv("FROM_EMAIL", "fraud-alert@frauddetection.com")
        
        # Consumer configuration
        self.consumer_config = {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": "fraud-notification-service",
            "auto.offset.reset": "latest",  # Only process new messages
            "enable.auto.commit": True,
            "auto.commit.interval.ms": 5000,
        }
        
        if self.kafka_username and self.kafka_password:
            self.consumer_config.update({
                "security.protocol": "SASL_SSL",
                "sasl.mechanism": "PLAIN",
                "sasl.username": self.kafka_username,
                "sasl.password": self.kafka_password,
            })
        else:
            self.consumer_config["security.protocol"] = "PLAINTEXT"
        
        try:
            self.consumer = Consumer(self.consumer_config)
            self.consumer.subscribe([self.topic])
            logger.info(f"Kafka Consumer initialized for topic: {self.topic}")
        except Exception as e:
            logger.error(f"Failed to initialize Kafka Consumer: {str(e)}")
            raise e
        
        self.running = False
        
        # Configure graceful shutdown
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)
    
    def send_email(self, transaction_data: Dict[str, Any]):
        """Send fraud alert email via MailDev"""
        try:
            # Extract transaction details
            transaction_id = transaction_data.get('transaction_id', 'N/A')
            user_id = transaction_data.get('user_id', 'N/A')
            amount = transaction_data.get('amount', 0.0)
            currency = transaction_data.get('currency', 'USD')
            merchant = transaction_data.get('merchant', 'Unknown')
            location = transaction_data.get('location', 'Unknown')
            timestamp = transaction_data.get('timestamp', 'N/A')
            prediction = transaction_data.get('prediction', 0)
            fraud_probability = transaction_data.get('fraud_probability', 0.0)
            
            # Only send email if it's predicted as fraud
            if prediction != 1:
                return
            
            # Create email
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'🚨 FRAUD ALERT: Transaction {transaction_id}'
            msg['From'] = self.from_email
            msg['To'] = f'user_{user_id}@frauddetection.com'
            
            # Create HTML email body
            html_body = f"""
            <html>
              <head>
                <style>
                  body {{ font-family: Arial, sans-serif; }}
                  .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                  .alert {{ background-color: #ff4444; color: white; padding: 15px; border-radius: 5px; }}
                  .details {{ background-color: #f5f5f5; padding: 15px; margin-top: 20px; border-radius: 5px; }}
                  .detail-row {{ margin: 10px 0; }}
                  .label {{ font-weight: bold; }}
                  .warning {{ color: #ff4444; font-weight: bold; }}
                </style>
              </head>
              <body>
                <div class="container">
                  <div class="alert">
                    <h2>⚠️ FRAUD ALERT</h2>
                    <p>A potentially fraudulent transaction has been detected on your account.</p>
                  </div>
                  
                  <div class="details">
                    <h3>Transaction Details:</h3>
                    <div class="detail-row">
                      <span class="label">Transaction ID:</span> {transaction_id}
                    </div>
                    <div class="detail-row">
                      <span class="label">User ID:</span> {user_id}
                    </div>
                    <div class="detail-row">
                      <span class="label">Amount:</span> {currency} {amount:.2f}
                    </div>
                    <div class="detail-row">
                      <span class="label">Merchant:</span> {merchant}
                    </div>
                    <div class="detail-row">
                      <span class="label">Location:</span> {location}
                    </div>
                    <div class="detail-row">
                      <span class="label">Timestamp:</span> {timestamp}
                    </div>
                    <div class="detail-row">
                      <span class="label warning">Fraud Probability:</span> 
                      <span class="warning">{fraud_probability * 100:.2f}%</span>
                    </div>
                  </div>
                  
                  <div style="margin-top: 20px; padding: 15px; background-color: #fff3cd; border-radius: 5px;">
                    <p><strong>⚡ Immediate Action Required:</strong></p>
                    <ul>
                      <li>If you did NOT authorize this transaction, contact us immediately</li>
                      <li>Review your recent account activity</li>
                      <li>Consider changing your password</li>
                      <li>Monitor your account for any unusual activity</li>
                    </ul>
                  </div>
                  
                  <div style="margin-top: 20px; color: #666; font-size: 12px;">
                    <p>This is an automated fraud detection alert. Please do not reply to this email.</p>
                    <p>© 2025 Fraud Detection System. All rights reserved.</p>
                  </div>
                </div>
              </body>
            </html>
            """
            
            # Attach HTML body
            html_part = MIMEText(html_body, 'html')
            msg.attach(html_part)
            
            # Send email via MailDev SMTP
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.send_message(msg)
            
            logger.info(f"✅ Fraud alert email sent for transaction {transaction_id} "
                       f"(User: {user_id}, Amount: {currency} {amount:.2f}, "
                       f"Probability: {fraud_probability * 100:.2f}%)")
            
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
    
    def process_message(self, message: Dict[str, Any]):
        """Process fraud prediction message and send notification"""
        try:
            self.send_email(message)
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
    
    def run(self):
        """Start consuming fraud predictions and sending notifications"""
        self.running = True
        logger.info("🚀 Fraud Notification Service started...")
        logger.info(f"📧 MailDev SMTP: {self.smtp_host}:{self.smtp_port}")
        logger.info(f"📨 Listening to Kafka topic: {self.topic}")
        
        try:
            while self.running:
                msg = self.consumer.poll(timeout=1.0)
                
                if msg is None:
                    continue
                
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        logger.debug(f"Reached end of partition {msg.partition()}")
                    else:
                        logger.error(f"Consumer error: {msg.error()}")
                    continue
                
                try:
                    # Parse message
                    transaction_data = json.loads(msg.value().decode('utf-8'))
                    logger.info(f"📥 Received prediction: {transaction_data.get('transaction_id')}")
                    
                    # Process and send notification
                    self.process_message(transaction_data)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse message: {str(e)}")
                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}")
        
        finally:
            self.shutdown()
    
    def shutdown(self, signum=None, frame=None):
        """Graceful shutdown"""
        if self.running:
            logger.info("⏹️  Shutting down notification service...")
            self.running = False
            if self.consumer:
                self.consumer.close()
            logger.info("✅ Notification service stopped")


if __name__ == "__main__":
    service = FraudNotificationService()
    service.run()
