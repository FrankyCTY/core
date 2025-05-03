# Glossary

## Core Architecture Terms

### Event Bus
- **Definition**: Central event distribution system in Home Assistant
- **Purpose**: Enables loose coupling between components
- **Implementation**: `homeassistant/core.py` - EventBus class

### State Machine
- **Definition**: System for tracking and managing entity states
- **Purpose**: Centralized state management
- **Implementation**: `homeassistant/core.py` - StateMachine class

### Service Registry
- **Definition**: System for managing service definitions and execution
- **Purpose**: Standardized interface for device control
- **Implementation**: `homeassistant/core.py` - ServiceRegistry class

## Component System

### Integration
- **Definition**: Module that connects Home Assistant to external devices or services
- **Purpose**: Extends Home Assistant's capabilities
- **Location**: `homeassistant/components/`

### Entity
- **Definition**: Representation of a device, service, or system in Home Assistant
- **Purpose**: Provides state and control interface
- **Types**: Device entities, service entities, system entities

## Protocol Support

### HTTP/REST
- **Definition**: Standard web protocol for device communication
- **Purpose**: Common integration method
- **Implementation**: Various HTTP clients and servers

### BLE
- **Definition**: Bluetooth Low Energy protocol
- **Purpose**: Local wireless device communication
- **Implementation**: Various BLE libraries

### Zigbee
- **Definition**: Wireless mesh networking protocol
- **Purpose**: Smart home device communication
- **Implementation**: Various Zigbee libraries

### Z-Wave
- **Definition**: Wireless communication protocol
- **Purpose**: Home automation device control
- **Implementation**: Various Z-Wave libraries

## ESPHome Assist Satellite
- **Purpose**: Voice assistant satellite implementation for ESPHome devices
- **Role**: Processes audio data and manages voice assistant functionality
- **Key Features**:
  - Audio streaming via WebSocket binary messages
  - Voice processing pipeline integration
  - Real-time audio processing
- **Integration**: Connects ESPHome devices to Home Assistant's voice assistant system

## WebSocket Binary Message Handling
- **Purpose**: Efficient binary data transmission over WebSocket connections
- **Key Components**:
  - Handler Registration System (max 255 handlers)
  - Binary Message Protocol (1-byte handler ID + payload)
  - Backpressure Management
- **Implementation**: `homeassistant/components/websocket_api/connection.py`

## Voice Assistant Pipeline
- **Purpose**: Manages the flow of audio data and voice processing
- **Components**:
  - Audio Input Stage
  - Wake Word Detection
  - Speech Recognition
  - Command Processing
  - Text-to-Speech Output
- **Transport Options**:
  - WebSocket API (push/pull hybrid)
  - UDP Streaming (real-time)

## UDP Audio Streaming
- **Purpose**: Real-time audio transmission for voice assistant
- **Key Components**:
  - VoiceAssistantUDPServer: Manages UDP communication
  - Audio Queue: Buffers incoming audio data
  - Processing Pipeline: Handles audio processing
- **Features**:
  - Low latency audio transmission
  - Direct device-to-server communication
  - Dynamic port allocation
- **Implementation**: `homeassistant/components/esphome/assist_satellite.py`

## Audio Processing Pipeline
- **Purpose**: Processes audio data from capture to response
- **Stages**:
  1. Audio Capture (UDP/WebSocket)
  2. Wake Word Detection
  3. Speech Recognition
  4. Command Processing
  5. Text-to-Speech Generation
  6. Audio Response
- **Implementation**: Distributed across ESPHome and Home Assistant components

## Auto Integration Detection

### SSDP (Simple Service Discovery Protocol)
- **Purpose**: Protocol for network service discovery
- **Role**: Enables automatic discovery of UPnP devices on the local network
- **Implementation**: Used in Home Assistant for device discovery and integration matching
- **Use Cases**: Media players, network cameras, smart TVs

### Zeroconf (mDNS/Bonjour)
- **Purpose**: Local network service discovery protocol
- **Role**: Enables automatic discovery of services on the local network
- **Implementation**: Uses multicast DNS for service discovery
- **Use Cases**: Printers, IoT devices, local services

### DHCP Discovery
- **Purpose**: Network device discovery via DHCP
- **Role**: Monitors DHCP traffic for device presence
- **Implementation**: Watches DHCP requests and responses
- **Use Cases**: Network devices, IoT hubs

### Bluetooth Discovery
- **Purpose**: Bluetooth device discovery
- **Role**: Scans for Bluetooth and BLE devices
- **Implementation**: Uses platform-specific Bluetooth APIs
- **Use Cases**: BLE devices, sensors, beacons

### HomeKit Discovery
- **Purpose**: Apple HomeKit device discovery
- **Role**: Discovers and pairs with HomeKit devices
- **Implementation**: Uses HomeKit protocol for discovery
- **Use Cases**: HomeKit-compatible devices

### Cloud SDK Discovery
- **Purpose**: Cloud-connected device discovery
- **Role**: Interfaces with cloud services for device discovery
- **Implementation**: Uses vendor-specific cloud APIs
- **Use Cases**: Cloud-connected devices, services

### Manual Configuration
- **Purpose**: User-initiated device setup
- **Role**: Provides guided setup for complex devices
- **Implementation**: Integration-specific config flows
- **Use Cases**: Complex devices, custom setups

## Integration Components

### Integration Matcher
- **Purpose**: Matches discovered devices to appropriate integrations
- **Role**: Analyzes device characteristics and manifest patterns
- **Implementation**: Defined in manifest.json files
- **Types**: Protocol-specific matchers (SSDP, Zeroconf, DHCP, etc.)

### Configuration Flow
- **Purpose**: Handles the setup process for discovered devices
- **Role**: Guides users through device configuration
- **Implementation**: Integration-specific ConfigFlow class
- **Types**: Protocol-specific steps (SSDP, Zeroconf, DHCP, etc.)

### Manifest Pattern
- **Purpose**: Defines discovery criteria for integrations
- **Role**: Specifies how to identify and match devices
- **Implementation**: JSON configuration in manifest.json
- **Types**: Protocol-specific patterns and matchers

## Discovery Protocols & Methods

### MQTT Discovery
- **Purpose**: Automatic device discovery via MQTT messages
- **Role**: Enables devices to self-register with Home Assistant
- **Implementation**: Uses MQTT topics for discovery and state updates
- **Key Features**:
  - Automatic entity creation
  - Device grouping
  - State updates via MQTT
  - Retained messages for persistence
- **Use Cases**: 
  - Custom IoT devices
  - Bridge integrations
  - DIY automation projects 