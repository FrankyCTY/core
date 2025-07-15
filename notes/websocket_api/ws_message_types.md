# WebSocket Message Types in Home Assistant

## 1. Overview

The Home Assistant WebSocket API supports two types of messages:
- Text Messages (JSON)
- Binary Messages (Raw Bytes)

Each type serves different purposes and has specific use cases based on the nature of the data being transmitted.

## 2. Text Messages (JSON)

### Purpose
Text messages are used for structured data communication, primarily for:
- Command/control operations
- State updates
- Event notifications
- Authentication
- Configuration changes

### Message Format
All text messages are JSON-formatted and follow a consistent structure:
```json
{
    "id": 1,                    // Message identifier
    "type": "command_type",     // Command type
    "data": {                   // Command-specific data
        "key": "value"
    }
}
```

### Common Use Cases
1. **Authentication**
   ```json
   {
       "type": "auth",
       "access_token": "..."
   }
   ```

2. **Service Calls**
   ```json
   {
       "id": 1,
       "type": "call_service",
       "domain": "light",
       "service": "turn_on",
       "target": {
           "entity_id": "light.living_room"
       }
   }
   ```

3. **State Updates**
   ```json
   {
       "id": 2,
       "type": "event",
       "event": {
           "data": {
               "new_state": {
                   "entity_id": "light.living_room",
                   "state": "on"
               }
           }
       }
   }
   ```

### Features
- Message batching/coalescing support
- Structured error handling
- Automatic JSON validation
- Support for message queuing

## 3. Binary Messages

### Purpose
Binary messages are optimized for:
- Audio streaming
- Video streaming
- File transfers
- Raw data transmission
- Any scenario where JSON serialization would be inefficient

### Message Format
Binary messages follow a specific protocol:
```
[Handler ID (1 byte)][Payload (remaining bytes)]
```

Example from assist_pipeline:
```python
# Binary message structure
handler_id = msg_data[0]  # First byte is handler ID
payload = msg_data[1:]    # Rest is the actual data

# Audio streaming handler
def handle_binary(_hass, _connection, data: bytes):
    audio_queue.put_nowait(data)
```

### Common Use Cases
1. **Audio Streaming** (assist_pipeline)
   ```python
   def handle_binary(
       _hass: HomeAssistant,
       _connection: websocket_api.ActiveConnection,
       data: bytes,
   ) -> None:
       # Forward to STT audio stream
       audio_queue.put_nowait(data)
   ```

2. **Video Streaming** (camera)
   - Raw video frames
   - Compressed video data
   - Camera snapshots

3. **File Transfers**
   - Large data transfers
   - Binary file uploads/downloads

### Features
- Efficient raw data transfer
- No JSON parsing overhead
- Direct binary data handling
- Connection-specific handlers

## 4. Message Processing Flow

### Text Message Processing
```python
# In WebSocketHandler._async_websocket_command_phase:
if msg_type is WSMsgType.TEXT:
    command_msg_data = json_loads(msg_data)
    async_handle_str(command_msg_data)
```

### Binary Message Processing
```python
# In WebSocketHandler._async_websocket_command_phase:
if msg_type is WSMsgType.BINARY:
    handler = msg_data[0]  # Get handler ID
    payload = msg_data[1:] # Get payload
    async_handle_binary(handler, payload)
```

## 5. When to Use Each Type

### Use Text Messages When:
- Sending commands
- Receiving state updates
- Handling events
- Authentication
- Configuration changes
- Any structured data exchange

### Use Binary Messages When:
- Streaming audio/video
- Transferring large files
- Sending raw sensor data
- Any case where JSON serialization would be inefficient
- When direct binary data handling is required

## 6. Error Handling

### Text Messages
- JSON validation errors
- Command format errors
- Authentication errors
- Service call errors

### Binary Messages
- Invalid handler ID
- Handler execution errors
- Connection errors
- Data processing errors

## 7. Performance Considerations

### Text Messages
- JSON parsing overhead
- Message batching available
- Memory efficient for small messages
- Good for frequent, small updates

### Binary Messages
- No parsing overhead
- Efficient for large data
- Direct memory access
- Better for streaming scenarios

## 8. Related Components

### Text Message Heavy
- State management
- Event system
- Service calls
- Configuration
- Authentication

### Binary Message Heavy
- assist_pipeline (audio)
- camera (video)
- stream (media)
- File transfer components
- Raw sensor data components 