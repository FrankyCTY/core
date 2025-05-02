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