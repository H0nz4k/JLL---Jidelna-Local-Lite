# JLL ELATEC auto-detection 0.4.2

## HIL metadata (reálné zařízení)

```text
device:         COM7
description:    Serial RFID Device (COM7)
manufacturer:   Elatec
product:        None
serial_number:  (prázdné)
vid/pid:        0x09D8 / 0x0420
hwid:           USB VID:PID=09D8:0420 SER= LOCATION=1-1
```

Driver soubor `subser.sys` / výrobce ovladače Microsoft **není** identifikátor.

## Matching

1. Primární: `manufacturer` case-insensitive obsahuje `elatec`
2. Fallback (HIL-proven): USB VID:PID `09D8:0420` (pole `vid`/`pid` nebo `hwid`)

**Nepoužívá se** samotný popis `Serial RFID Device` bez Elatec/VID.

## Chování

| Nález | Stav |
| --- | --- |
| 0 | NOT_FOUND – aplikace běží, čtečka DISCONNECTED |
| 1 | FOUND – automatický výběr aktuálního COM |
| 2+ | AMBIGUOUS – bez náhodného výběru; preference `reader_device_serial` pokud unikátní |

COM číslo je runtime, ne identita. Po odpojení/připojení (i na jiný COM) AUTO reader znovu resolve.

## Config

```text
reader_mode: auto_elatec | manual   (default nových instalací: auto_elatec)
reader_port: jen MANUAL
reader_device_serial: volitelná preference při více ELATEC
```

Legacy JSON bez `reader_mode` + nastavený `reader_port` → načte se jako **manual** (bez překvapivé změny).

## Manual override

Administrace → Čtečka: Automaticky – ELATEC / Ručně vybrat COM.
