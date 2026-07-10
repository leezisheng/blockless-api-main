# content/

Curated content served by the API, split by kind:

| dir | what |
|-----|------|
| `boards/` | Board definitions returned by `/v1/boards` (id, display name, chip family, pin-allocation flag). |
| `chips/` | Per-chip pin-fact tables used by the pin allocator. |
| `enclosure/board_profiles/` | Per-board case footprints. |
| `enclosure/module_profiles/` | Per-module footprints for the placement solver. |
| `models/` | License-cleared 3D component assets (`.glb`/`.obj`) served by `/v1/models`. |
| `recommendation/` | Board/module display models and purchase links. |

This snapshot ships a small set of example entries; production deployments load a
larger curated catalog from the same layout.
