# API Errors and Rate Limits

## Rate limits
Error 429 means the rate limit was exceeded. The default limit is 60 requests per minute on Starter and 600 requests per minute on Pro. Customers should slow down and retry with exponential backoff.

## Authentication errors
Error 401 means the API key is invalid or revoked. API keys are created and rotated under Settings, then Developer.

## Server errors
Error 500 or 503 means a problem on the Acme Cloud side. Collect the request ID, the endpoint and the timestamp. If the error continues for more than 1 hour, support opens a ticket with engineering. Large export requests can time out, and customers should use the asynchronous export endpoint for big datasets.
