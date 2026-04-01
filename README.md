# Virtualization and Linux Network Setup with WireGuard

## Overview

This project involves creating a virtualized network environment using two Linux machines. The objective is to configure network connectivity between them and establish a secure VPN tunnel using WireGuard. Additionally, network traffic analysis is performed using Wireshark to verify standard connectivity versus encrypted VPN traffic.

## Prerequisites

- **Hypervisor:** Oracle VM VirtualBox, VMWare, Hyper-V, or similar.
  - _Note:_ If your CPU does not support VT-x, use VirtualBox version 5.2 or earlier.
- **Operating Systems:** Two Linux distributions (e.g., Ubuntu or Arch/EndeavourOS).
- **Tools:**
  - Wireshark (for packet capture)
  - Text Editor (for configuration files)
  - Video recording software (for demonstration)

## Installation & Setup

### 1. Virtual Machine Creation

1.  Download the ISO images for your chosen Linux distributions.
2.  Create **two** virtual machines using your hypervisor of choice.
3.  Install the operating systems on both VMs.

### 2. System Updates

Update the system packages via the command line interface.

**For Arch Linux / EndeavourOS:**

```bash
yay -Syu
pacman -S net-tools
```

**For Ubuntu:**

```bash
sudo apt update
sudo apt upgrade
```

### 3. Network Connectivity Verification

1.  Identify the IP address of each machine:
    ```bash
    ifconfig
    ```
2.  Verify connectivity by pinging one machine from the other:
    ```bash
    ping <IP_ADDRESS_OF_OTHER_VM>
    ```

## VPN Configuration (WireGuard)

Install and configure WireGuard on both machines to create a secure tunnel.

### Installation

**Ubuntu:**

```bash
sudo apt install wireguard-dkms
sudo reboot -h now
```

**Arch Linux:**
_(Ensure `net-tools` is installed as per step 2)_

### Configuration

1.  Navigate to the configuration directory:
    ```bash
    cd /etc/wireguard
    ```
2.  Set secure permissions for key generation:
    ```bash
    sudo umask 077
    ```
3.  Generate keys and configure interfaces (follow standard WireGuard quickstart guides).
4.  Save the configuration:
    ```bash
    sudo wg showconf wg0 > wg0.conf
    ```
5.  Restart the interface:
    ```bash
    sudo wg-quick down wg0
    sudo wg-quick up wg0
    ```
    _Note: All commands must be executed as root (using `sudo` or `su`)._

### VPN Verification

1.  Identify the IP address assigned to the `wg0` interface on both machines.
2.  Ping the `wg0` IP address of the remote machine from the local machine.
3.  Capture traffic using Wireshark during this ping test.

## Documentation & Artifacts

The following artifacts should be generated to document the setup and verification process:

### 1. Screenshots

Capture screenshots for the following steps:

- Hypervisor selection and VM creation.
- System update process.
- Network connectivity checks (`ifconfig`, standard `ping`).
- WireGuard installation and configuration.
- Wireshark analysis.

### 2. Video Demonstration

- Record a video (max 5 minutes) demonstrating the VPN functionality.
- Verify identity within the command line (e.g., display username/hostname) during the demo.

### 3. Wireshark Captures

Save `.pcapng` files for the following scenarios:

- **Standard Traffic:** Ping between VMs without VPN.
- **VPN Traffic:** Ping between VMs using the WireGuard interface (`wg0`).

## Bonus Features (Optional)

Deploy custom software developed in a previous module onto the virtual machines.

1.  **Deployment:** Install the client on one VM and the server on the other.
2.  **File Transfer:** Perform a file transfer between the two machines.
3.  **Verification:**
    - Record a video demonstration of the transfer.
    - Capture Wireshark traffic during the file transfer.
4.  **Advanced Bonus:** Perform the file transfer through the configured WireGuard VPN tunnel.

## Repository Structure

Recommended structure for storing project artifacts:

```text
.
├── docs/
│   ├── screenshots/
│   ├── videos/
│   │   ├── vpn_demo.mp4
│   │   └── bonus_demo.mp4
│   └── captures/
│       ├── vm_ping.pcapng
│       ├── wg_ping.pcapng
│       └── bonus_transfer.pcapng
├── scripts/
│   └── (any automation scripts used)
└── README.md
```
