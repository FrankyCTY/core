# Learning Log

## 2024-05-03

- **Analyzed Home Assistant's WebSocket API message handling system**
  - Learned about sophisticated backpressure management using **deque** and **Future-based signaling**
  - Understood the message coalescing strategy for balancing latency vs throughput
  - Discovered the **two-tier backpressure detection system**(soft and hard limits)
  - Explored the role of authentication in buffer size management
  - Documented the complete message flow from queuing to sending 

- **WebSocket Binary Message Handling**
  - Analyzed the binary message protocol structure (1-byte handler ID + payload)
  - Understood the handler registration system (max 255 handlers per connection)
  - Explored the message processing flow from client to handler
  - Documented key decision points in the binary message system design

- **ESPHome Assist Satellite**
  - Studied the integration of ESPHome devices as voice assistant satellites
  - Analyzed the audio streaming pipeline and binary message handling
  - Documented the communication flow between client, WebSocket, and satellite
  - Explored the role of binary handlers in real-time audio processing 

## 2024-04-30

### WebSocket API in Home Assistant Core
- Analyzed the WebSocket API setup and connection flow in Home Assistant
- Key components identified with clear separation of concerns:
  - `WebsocketAPIView`: Main entry point for WebSocket connections
  - `WebSocketHandler`: Manages protocol-level concerns and connection lifecycle
  - `ActiveConnection`: Handles authenticated session and message processing
  - `AuthPhase`: Manages authentication process
- Learned about the three-phase connection process:
  1. Connection Establishment (WebSocketHandler)
  2. Authentication Phase (WebSocketHandler)
  3. Command Phase (ActiveConnection)
- Discovered performance optimizations:
  - Message coalescing to reduce writes
  - Backpressure handling to prevent memory issues
  - Buffer size management (1MiB after auth)
- Understood the security measures:
  - Required authentication before command processing
  - Connection termination on auth failure/timeout
  - Buffer limits during auth phase
  - Clear separation between protocol and business logic 
