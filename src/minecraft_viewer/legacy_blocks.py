"""Java pre-flattening IDs and metadata -> shared named render materials.

ID registry: PrismarineJS/minecraft-data data/pc/1.12/blocks.json.
Keep unknown extended IDs distinct; never alias them to vanilla blocks.
"""
import json
from pathlib import Path

import numpy as np

DYES = 'white orange magenta light_blue yellow lime pink gray light_gray cyan purple blue brown green red black'.split()
WOODS = 'oak spruce birch jungle acacia dark_oak'.split()
LEGACY_NAMES = {int(k): v for k, v in json.loads(Path(__file__).with_name('data').joinpath('legacy_blocks.json').read_text()).items()}
ALIASES = {
    'grass':'grass_block', 'flowing_water':'water', 'flowing_lava':'lava',
    'noteblock':'note_block', 'golden_rail':'powered_rail', 'web':'cobweb',
    'deadbush':'dead_bush', 'yellow_flower':'dandelion', 'brick_block':'bricks',
    'mob_spawner':'spawner', 'lit_furnace':'furnace', 'standing_sign':'oak_sign',
    'wooden_door':'oak_door', 'stone_stairs':'cobblestone_stairs', 'wall_sign':'oak_wall_sign',
    'wooden_pressure_plate':'oak_pressure_plate', 'lit_redstone_ore':'redstone_ore',
    'unlit_redstone_torch':'redstone_torch', 'snow_layer':'snow', 'snow':'snow_block',
    'reeds':'sugar_cane', 'fence':'oak_fence', 'portal':'nether_portal',
    'lit_pumpkin':'jack_o_lantern', 'unpowered_repeater':'repeater', 'powered_repeater':'repeater',
    'trapdoor':'oak_trapdoor', 'melon_block':'melon', 'fence_gate':'oak_fence_gate',
    'waterlily':'lily_pad', 'nether_brick':'nether_bricks', 'lit_redstone_lamp':'redstone_lamp',
    'wooden_button':'oak_button', 'unpowered_comparator':'comparator', 'powered_comparator':'comparator',
    'quartz_ore':'nether_quartz_ore', 'slime':'slime_block', 'hardened_clay':'terracotta',
    'standing_banner':'white_banner', 'wall_banner':'white_wall_banner',
    'daylight_detector_inverted':'daylight_detector', 'double_stone_slab2':'red_sandstone_slab',
    'stone_slab2':'red_sandstone_slab', 'purpur_double_slab':'purpur_slab',
    'end_bricks':'end_stone_bricks', 'magma':'magma_block', 'red_nether_brick':'red_nether_bricks',
}


def legacy_name(block_id, data=0):
    block_id, data = int(block_id), int(data) & 15
    family = {35:'wool', 95:'stained_glass', 159:'terracotta', 160:'stained_glass_pane',
              171:'carpet', 251:'concrete', 252:'concrete_powder'}.get(block_id)
    if family:
        name = f'{DYES[data]}_{family}'
    elif block_id in (5,6,17,18,125,126,161,162):
        kind = {5:'planks',6:'sapling',17:'log',18:'leaves',125:'slab',126:'slab',161:'leaves',162:'log'}[block_id]
        variant = (data & 1)+4 if block_id in (161,162) else data & (3 if block_id in (17,18) else 7)
        name = f'{WOODS[min(variant,5)]}_{kind}'
    else:
        variants = {
            1: 'stone granite polished_granite diorite polished_diorite andesite polished_andesite',
            3: 'dirt coarse_dirt podzol', 12:'sand red_sand', 19:'sponge wet_sponge',
            24:'sandstone chiseled_sandstone cut_sandstone', 31:'dead_bush grass fern',
            38:'poppy blue_orchid allium azure_bluet red_tulip orange_tulip white_tulip pink_tulip oxeye_daisy',
            97:'infested_stone infested_cobblestone infested_stone_bricks infested_mossy_stone_bricks infested_cracked_stone_bricks infested_chiseled_stone_bricks',
            98:'stone_bricks mossy_stone_bricks cracked_stone_bricks chiseled_stone_bricks',
            139:'cobblestone_wall mossy_cobblestone_wall',
            155:'quartz_block chiseled_quartz_block quartz_pillar quartz_pillar quartz_pillar',
            168:'prismarine prismarine_bricks dark_prismarine',
            175:'sunflower lilac tall_grass large_fern rose_bush peony',
            179:'red_sandstone chiseled_red_sandstone cut_red_sandstone',
        }
        if block_id in (43,44):
            name = 'stone_slab sandstone_slab petrified_oak_slab cobblestone_slab brick_slab stone_brick_slab nether_brick_slab quartz_slab'.split()[data & 7]
        elif block_id in variants:
            names = variants[block_id].split()
            variant = data & 7 if block_id == 175 else data
            name = names[variant] if variant < len(names) else names[0]
        else:
            name = LEGACY_NAMES.get(block_id, f'legacy_unknown_{block_id}')
            name = ALIASES.get(name, name)
    return 'minecraft:' + name


def legacy_pairs(section):
    """Unpack signed NBT bytes, low-nibble-first metadata and optional Add IDs."""
    ids = np.asarray(section.get('Blocks', np.zeros(4096)), dtype=np.int64) & 255
    def nibbles(key):
        packed = np.asarray(section.get(key, np.zeros(2048)), dtype=np.int64) & 255
        result = np.empty(4096, dtype=np.int64)
        result[0::2] = packed & 15
        result[1::2] = packed >> 4
        return result
    return ((ids | (nibbles('Add') << 8)) << 4) | nibbles('Data')


def legacy_names(section):
    pairs = legacy_pairs(section)
    unique, inverse = np.unique(pairs, return_inverse=True)
    return np.array([legacy_name(p >> 4, p & 15) for p in unique], dtype=object)[inverse]
