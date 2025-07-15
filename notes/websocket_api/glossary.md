# WebSocket API Glossary

## Core Components

### WebSocketHandler
- **Definition**: Core class managing WebSocket connection lifecycle and message handling
- **Key Responsibilities**:
  - Message queuing
  - Backpressure detection
  - Writer task management
  - Connection cleanup
- **File**: `http.py`

### ActiveConnection
- **Definition**: Represents an authenticated WebSocket connection
- **Key Properties**:
  - `can_coalesce`: Controls message batching behavior
  - `get_description`: Provides connection identification
- **File**: `connection.py`

### AuthPhase
- **Definition**: Manages the authentication process for WebSocket connections
- **Key Methods**:
  - `async_handle`: Process auth message
  - `validate_credentials`: Verify client identity
  - `create_connection`: Initialize authenticated session
- **File**: `auth.py`

## Message Handling

### Message Coalescing
- **Definition**: Technique of batching multiple messages together to reduce network operations
- **Purpose**: Balances latency vs throughput in message sending
- **Implementation**: 
  - Controlled by `can_coalesce` flag in ActiveConnection
  - Uses event loop scheduling to accumulate messages
  - Messages are batched before the writer is unblocked
- **Benefits**:
  - Reduces network overhead
  - Maintains reasonable latency
  - Allows natural message grouping within event loop ticks

### Backpressure Management
- **Definition**: System for controlling message flow when sender produces messages faster than receiver can process
- **Implementation**: Uses deque for message queuing, Future-based signaling, and size monitoring
- **Key Components**: 
  - MAX_PENDING_MSG (hard limit)
  - PENDING_MSG_PEAK (soft limit)
  - Message coalescing
  - Dynamic buffer sizing

### Message Queue
- **Definition**: Data structure storing pending messages before sending
- **Implementation**: Uses `deque` for efficient append/pop operations
- **Purpose**: Enables message batching and backpressure management

## Configuration Constants

### MAX_PENDING_MSG
- **Definition**: Hard limit for message queue size
- **Purpose**: Triggers connection termination when exceeded
- **Value**: 512 messages

### PENDING_MSG_PEAK
- **Definition**: Soft limit for message queue size
- **Purpose**: Triggers warning and monitoring when exceeded
- **Value**: 128 messages

### PENDING_MSG_PEAK_TIME
- **Definition**: Duration for sustained backpressure check
- **Purpose**: Determines how long queue can stay above peak before termination
- **Value**: 5 seconds

## Security Terms

### Authentication Phase
- **Definition**: Initial phase of WebSocket connection requiring client credentials
- **Duration**: 10 seconds timeout
- **Requirements**:
  - Must complete before command processing
  - Strict timeout enforcement
  - Limited buffer size

### Buffer Size Management
- **Definition**: Dynamic adjustment of WebSocket write buffer
- **Default**: Limited during authentication
- **Post-Auth**: Increased to 1MiB
- **Purpose**: Optimizes performance while maintaining security 

## Binary Message Handling

### WebSocket Binary Message Handling
- **Purpose**: Efficient handling of real-time data streams in WebSocket connections
- **Role**: Enables direct binary data transfer without JSON serialization overhead
- **Key Components**:
  - Handler ID (1 byte): Identifies the message handler
  - Payload: Raw binary data
  - Binary Handlers: Connection-specific message processors
- **Use Cases**: Audio streaming, video streaming, large data transfers 