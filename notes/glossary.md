# Glossary

## WebSocket API Terms

### WebSocketHandler
A class that manages the WebSocket protocol and connection lifecycle in Home Assistant. It handles the HTTP upgrade to WebSocket, authentication phase, and protocol-level concerns like message queue management and connection cleanup.

### ActiveConnection
A class that manages authenticated WebSocket sessions and message processing. It handles business logic, command processing, user session management, and response formatting after successful authentication.

### AuthPhase
The authentication phase of a WebSocket connection. It validates client credentials and must complete within 10 seconds. If authentication fails or times out, the connection is terminated.

### Message Coalescing
A performance optimization technique where multiple messages are batched together before being sent over the WebSocket connection, reducing the number of writes and improving throughput.

### Backpressure
A mechanism to prevent memory issues by monitoring the message queue size. If the queue grows too large, the connection may be terminated to protect system resources. 