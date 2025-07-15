# ESPHome Assist Satellite UDP Audio Flow

## Initial Setup

The UDP audio flow begins with the integration setup in `homeassistant/components/esphome/assist_satellite.py`:

1. **Integration Entry Point**:
```python
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ESPHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Assist satellite entity."""
    entry_data = entry.runtime_data
    assert entry_data.device_info is not None
    if entry_data.device_info.voice_assistant_feature_flags_compat(
        entry_data.api_version
    ):
        async_add_entities([EsphomeAssistSatellite(entry)])
```

2. **Feature Detection**:
- The integration checks if the ESPHome device supports voice assistant features
- Feature flags are checked using `voice_assistant_feature_flags_compat`
- UDP support is determined by the device's capabilities

## UDP Server Initialization

The UDP server is initialized when needed in the `handle_pipeline_start` method:

```python
async def handle_pipeline_start(
    self,
    conversation_id: str,
    flags: int,
    audio_settings: VoiceAssistantAudioSettings,
    wake_word_phrase: str | None,
) -> int | None:
    # ... other initialization code ...
    
    # Check if UDP should be used
    if (feature_flags & VoiceAssistantFeature.SPEAKER) and not (
        feature_flags & VoiceAssistantFeature.API_AUDIO
    ):
        port = await self._start_udp_server()
        _LOGGER.debug("Started UDP server on port %s", port)
    
    # ... rest of the method ...
```

## UDP Server Implementation

The `VoiceAssistantUDPServer` class handles UDP communication:

```python
class VoiceAssistantUDPServer(asyncio.DatagramProtocol):
    """Receive UDP packets and forward them to the audio queue."""
    
    def __init__(
        self, audio_queue: asyncio.Queue[bytes | None], *args: Any, **kwargs: Any
    ) -> None:
        """Initialize protocol."""
        super().__init__(*args, **kwargs)
        self._audio_queue = audio_queue

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle incoming UDP packet."""
        if self.remote_addr is None:
            self.remote_addr = addr
        self._audio_queue.put_nowait(data)
```

## Audio Flow Sequence

1. **Initialization**:
   - User initiates voice assistant through Home Assistant
   - Integration checks device capabilities
   - If UDP is supported, server is started on a random port

2. **UDP Server Setup**:
   - Server binds to a random available port
   - Port number is sent to the ESPHome device
   - Device connects to the UDP server

3. **Audio Streaming**:
   - Audio data is sent in UDP packets
   - Each packet is queued for processing
   - Audio processing pipeline handles the data

## Key Components

### 1. UDP Server Management
- **Start**: `_start_udp_server()`
  - Creates UDP socket
  - Binds to random port
  - Sets up protocol handler
- **Stop**: `_stop_udp_server()`
  - Closes socket
  - Cleans up resources

### 2. Audio Queue
- **Purpose**: Buffer audio data between UDP and processing
- **Implementation**: `asyncio.Queue`
- **Size**: Dynamically managed based on backpressure

### 3. Audio Processing Pipeline
- **Input**: UDP packets from queue
- **Processing**: Voice recognition, command processing
- **Output**: Text-to-speech or command execution

## User Interaction Flow

1. **Initialization**:
```python
# User initiates voice assistant
await hass.services.async_call(
    "esphome",
    "start_voice_assistant",
    {"entity_id": "esphome.device_id"}
)
```

2. **Audio Capture**:
- User speaks into ESPHome device
- Device captures audio and sends via UDP
- Server receives and processes audio

3. **Command Processing**:
- Audio is converted to text
- Command is processed
- Response is generated

4. **Response**:
- Text-to-speech response is sent back
- Device plays audio response

## Error Handling

1. **Connection Issues**:
```python
def error_received(self, exc: Exception) -> None:
    """Handle UDP errors."""
    _LOGGER.error("ESPHome Voice Assistant UDP server error received: %s", exc)
    self._audio_queue.put_nowait(None)  # Signal pipeline to stop
```

2. **Timeout Handling**:
- UDP server has timeout for inactivity
- Pipeline can be aborted if needed

## Performance Considerations

1. **Buffer Management**:
- Audio queue size is managed to prevent overflow
- Backpressure is handled through queue size limits

2. **Latency Optimization**:
- UDP chosen for lower latency
- Direct device-to-server communication
- Minimal processing overhead

## Debugging

Key logging points:
```python
_LOGGER.debug("Started UDP server on port %s", port)
_LOGGER.debug("Streaming %s audio samples", wav_file.getnframes())
_LOGGER.error("ESPHome Voice Assistant UDP server error received: %s", exc)
```

## Next Steps

1. **Implementation Details**:
   - Review `assist_satellite.py` for complete pipeline
   - Study `VoiceAssistantUDPServer` for UDP specifics
   - Examine audio processing pipeline

2. **Testing**:
   - Test UDP connection stability
   - Verify audio quality
   - Check error handling

3. **Optimization**:
   - Monitor buffer sizes
   - Check latency
   - Verify error recovery 