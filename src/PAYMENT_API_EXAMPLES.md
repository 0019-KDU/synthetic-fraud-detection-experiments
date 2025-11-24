# Payment API - Usage Examples

## API Endpoint
`http://64.227.176.139:5001/payment`

## How to Use with Postman

### 1. Health Check
**GET** `http://64.227.176.139:5001/health`

Response:
```json
{
  "status": "healthy",
  "service": "payment-api"
}
```

---

### 2. Submit Legitimate Payment
**POST** `http://64.227.176.139:5001/payment`

Headers:
```
Content-Type: application/json
```

Body (JSON):
```json
{
  "transaction_id": "3895742",
  "user_id": 5432,
  "amount": 45.99,
  "currency": "USD",
  "merchant": "Amazon",
  "location": "US"
}
```

Expected Response (200 OK):
```json
{
  "status": "success",
  "transaction_id": "3895742",
  "result": "legitimate",
  "fraud_probability": 0.0523,
  "risk_level": "LOW",
  "message": "Transaction approved",
  "details": {
    "user_id": 5432,
    "amount": 45.99,
    "currency": "USD",
    "merchant": "Amazon",
    "location": "US"
  }
}
```

---

### 3. Submit Fraudulent Payment (High Amount + Risky Merchant)
**POST** `http://64.227.176.139:5001/payment`

Body (JSON):
```json
{
  "transaction_id": "4021653",
  "user_id": 7890,
  "amount": 3500.00,
  "currency": "USD",
  "merchant": "FastMoneyX",
  "location": "CN"
}
```

Expected Response (200 OK):
```json
{
  "status": "success",
  "transaction_id": "4021653",
  "result": "fraud",
  "fraud_probability": 0.8734,
  "risk_level": "HIGH",
  "message": "Transaction blocked - suspected fraud",
  "details": {
    "user_id": 7890,
    "amount": 3500.0,
    "currency": "USD",
    "merchant": "FastMoneyX",
    "location": "CN"
  }
}
```

---

### 4. Submit Card Testing Transaction (Small Amount)
**POST** `http://64.227.176.139:5001/payment`

Body (JSON):
```json
{
  "transaction_id": "3745821",
  "user_id": 1000,
  "amount": 0.50,
  "currency": "USD",
  "merchant": "TestMerchant",
  "location": "US"
}
```

Expected Response (200 OK):
```json
{
  "status": "success",
  "transaction_id": "3745821",
  "result": "fraud",
  "fraud_probability": 0.7245,
  "risk_level": "HIGH",
  "message": "Transaction blocked - suspected fraud",
  "details": {
    "user_id": 1000,
    "amount": 0.5,
    "currency": "USD",
    "merchant": "TestMerchant",
    "location": "US"
  }
}
```

---

### 5. Invalid Request (Missing Required Fields)
**POST** `http://64.227.176.139:5001/payment`

Body (JSON):
```json
{
  "transaction_id": "3895742",
  "amount": 100.00
}
```

Expected Response (400 Bad Request):
```json
{
  "status": "error",
  "message": "Validation error: 'user_id' is a required property"
}
```

---

## Risk Levels

| Fraud Probability | Risk Level |
|-------------------|-----------|
| 0.0 - 0.39 | LOW |
| 0.40 - 0.69 | MEDIUM |
| 0.70 - 1.0 | HIGH |

---

## Testing Fraud Patterns

### Account Takeover
```json
{
  "transaction_id": "4100001",
  "user_id": 5234,
  "amount": 2500.00,
  "merchant": "QuickCash",
  "location": "US"
}
```
**Why fraud**: High amount from risky merchant

### Geographic Anomaly
```json
{
  "transaction_id": "4100002",
  "user_id": 3456,
  "amount": 1000.00,
  "merchant": "OnlineStore",
  "location": "RU"
}
```
**Why fraud**: Suspicious location (Russia)

### Merchant Collusion
```json
{
  "transaction_id": "4100003",
  "user_id": 2345,
  "amount": 850.00,
  "merchant": "GlobalDigital",
  "location": "US"
}
```
**Why fraud**: High-risk merchant over $300

---

## Deployment

Upload files:
```bash
scp "c:\Users\chira\Desktop\Source Code - Fraud Detection Solution from Scratch\src\producer\payment_api.py" root@64.227.176.139:/home/synthetic-fraud-detection-experiments/src/producer/

scp "c:\Users\chira\Desktop\Source Code - Fraud Detection Solution from Scratch\src\producer\requirements.txt" root@64.227.176.139:/home/synthetic-fraud-detection-experiments/src/producer/

scp "c:\Users\chira\Desktop\Source Code - Fraud Detection Solution from Scratch\src\docker-compose.yml" root@64.227.176.139:/home/synthetic-fraud-detection-experiments/src/
```

Build and start:
```bash
cd /home/synthetic-fraud-detection-experiments/src
docker compose build payment-api
docker compose up -d payment-api
docker compose logs -f payment-api
```

Open firewall:
```bash
ufw allow 5001/tcp
```

Test:
```bash
curl http://64.227.176.139:5001/health
```
