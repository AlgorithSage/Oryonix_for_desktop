# Windows base sandbox image — Packer template (stub, filled in Chunk 4)
#
# Customer supplies a licensed Windows 10/11 LTSC ISO.
# This template provisions it with:
#   - Python 3.11+
#   - pywinauto (UIA accessibility backend)
#   - nut.js (native input simulation)
#   - mss (screenshot)
#   - pywin32, comtypes
#   - trycua/cua guest agent (auto-start service)
#
# Usage:
#   packer build -var "windows_iso=path/to/licensed.iso" packer.pkr.hcl
#
# The user never sees this file or the resulting VM — Oryonix abstracts
# all sandbox lifecycle via trycua/cua SDK (Gap H).

variable "windows_iso" {
  type        = string
  description = "Path to customer-supplied, licensed Windows 10/11 LTSC ISO."
}

# Full build block implemented in Chunk 4
