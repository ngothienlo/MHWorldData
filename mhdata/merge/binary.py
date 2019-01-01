from typing import Type, Mapping, Iterable
from os.path import dirname, abspath, join
import re

from mhw_armor_edit import ftypes
from mhw_armor_edit.ftypes import am_dat, gmd, arm_up, itm, skl_pt_dat, eq_crt

from mhdata.io import create_writer, DataMap
from mhdata.load import load_data, schema
from mhdata.build import datafn
from mhdata.util import OrderedSet, bidict

# Writer used to write back updated data
writer = create_writer()

# Location of MHW binary data.
# Looks for a folder called /mergedchunks neighboring the main project folder.
# This folder should be created via WorldChunkTool, with each numbered chunk being
# moved into the mergedchunks folder in ascending order (with overwrite).
CHUNK_DIRECTORY = join(dirname(abspath(__file__)), "../../../mergedchunks")

# Mapping from GMD filename suffix to actual language code
lang_map = {
    'eng': 'en',
    'jpn': 'ja',
    'fre': 'fr',
    'ger': 'de',
    'ita': 'it',
    'spa': 'es',
    'ptB': 'pt',
    'pol': 'pl',
    'rus': 'ru',
    'kor': 'ko',
    'chT': 'zh',
    'ara': 'ar',
}

# Index based gender restriction
gender_list = [None, 'male', 'female', 'both']

# Index based item type
item_type_list = [
    'item', # Consumable / Trade
    'material', # Monster Material
    'endemic', # Endemic Life
    'ammo',
    'jewel'
]


def load_schema(schema: Type[ftypes.StructFile], relative_dir: str) -> ftypes.StructFile:
    "Uses an ftypes struct file class to load() a file relative to the chunk directory"
    with open(join(CHUNK_DIRECTORY, relative_dir), 'rb') as f:
        return schema.load(f)

def load_text(basepath: str) -> Mapping[int, Mapping[str, str]]:
    """Parses a series of GMD files, returning a mapping from index -> language -> value
    
    The given base path is the relative directory from the chunk folder,
    excluding the _eng.gmd ending. All GMD files starting with the given basepath
    and ending with the language are combined together into a single result.
    """
    results = {}
    for ext_lang, lang in lang_map.items():
        data = load_schema(gmd.Gmd, f"{basepath}_{ext_lang}.gmd")
        for idx, value_obj in enumerate(data.items):
            if idx not in results:
                results[idx] = {}
            value = value_obj.value
            value = re.sub(r"( )*\r?\n( )*", " ", value)
            value = re.sub(r"( )?<ICON ALPHA>", " α", value)
            value = re.sub(r"( )?<ICON BETA>", " β", value)
            value = re.sub(r"( )?<ICON GAMMA>", " γ", value)
            results[idx][lang] = (value
                                    .replace("<STYL MOJI_YELLOW_DEFAULT>[1]</STYL>", "[1]")
                                    .replace("<STYL MOJI_YELLOW_DEFAULT>[2]</STYL>", "[2]")
                                    .replace("<STYL MOJI_YELLOW_DEFAULT>[3]</STYL>", "[3]")
                                    .replace("<STYL MOJI_YELLOW_DEFAULT>", "")
                                    .replace("<STYL MOJI_LIGHTBLUE_DEFAULT>", "")
                                    .replace("</STYL>", "")).strip()
    return results

def update_armor():
    "Populates and updates armor information using the armorset_base as a source of truth"
    
    armor_text = load_text("common/text/steam/armor")
    armorset_text = load_text("common/text/steam/armor_series")
    item_text = load_text("common/text/steam/item")

    # Parses binary armor data, mapped by the english name
    armor_data = {}    
    for armor_entry in load_schema(am_dat.AmDat, "common/equip/armor.am_dat").entries:
        if armor_entry.gender == 0: continue
        if armor_entry.order == 0: continue
        name_en = armor_text[armor_entry.gmd_name_index]['en']
        armor_data[name_en] = armor_entry

    # Parses craft data, mapped by the binary armor id
    armor_craft_data = {}
    for craft_entry in load_schema(eq_crt.EqCrt, "common/equip/armor.eq_crt"):
        armor_craft_data[craft_entry.equip_id] = craft_entry

    # Get number of times armor can be upgraded by rarity level.
    # Unk7 is max level pre-augment, Unk8 is max post-augment
    # Thanks to the MHWorld Modders for the above info
    rarity_upgrades = {}
    for entry in load_schema(arm_up.ArmUp, "common/equip/arm_upgrade.arm_up").entries:
        rarity_upgrades[entry.index + 1] = (entry.unk7 - 1, entry.unk8 - 1)

    # Get mapping from skill idx -> skill name en (as a bidict).
    # Discovered formula via inspecting mhw_armor_edit's source.
    skill_map = bidict()
    skill_text = load_text("common/text/vfont/skill_pt")
    for entry in load_schema(skl_pt_dat.SklPtDat, "common/equip/skill_point_data.skl_pt_dat").entries:
        skill_map[entry.index] = skill_text[entry.index * 3]['en']
    
    print("Binary data loaded")

    mhdata = load_data()
    print("Existing Data loaded. Using existing armorset data to drive new armor data.")

    # Will store results. Language lookup and validation will be in english
    new_armor_map = DataMap(languages="en")
    new_armorset_bonus_map = DataMap(languages="en")

    # Temporary storage for later processes
    all_set_skill_ids = OrderedSet()
    all_item_ids = OrderedSet()

    print("Populating armor data, keyed by the armorset data")
    next_armor_id = mhdata.armor_map.max_id + 1
    for armorset in mhdata.armorset_map.values():
        # Handle armor pieces
        for part, armor_name in datafn.iter_armorset_pieces(armorset):
            existing_armor = mhdata.armor_map.entry_of('en', armor_name)
            armor_binary = armor_data.get(armor_name)

            if not armor_binary:
                raise Exception(f"Failed to find binary armor data for {armor_name}")

            if armor_binary.set_skill1_lvl > 0:
                all_set_skill_ids.add(armor_binary.set_skill1)

            rarity = armor_binary.rarity + 1
            name_dict = armor_text[armor_binary.gmd_name_index]

            # Initial new armor data
            new_data = {
                'name': name_dict, # Override for translation support!
                'rarity': rarity,
                'type': part,
                'gender': gender_list[armor_binary.gender],
                'slot_1': armor_binary.gem_slot1_lvl,
                'slot_2': armor_binary.gem_slot2_lvl,
                'slot_3': armor_binary.gem_slot3_lvl,
                'defense_base': armor_binary.defense,
                'defense_max': armor_binary.defense + rarity_upgrades[rarity][0] * 2,
                'defense_augment_max': armor_binary.defense + rarity_upgrades[rarity][1] * 2,
                'defense_fire': armor_binary.fire_res,
                'defense_water': armor_binary.water_res,
                'defense_thunder': armor_binary.thunder_res,
                'defense_ice': armor_binary.ice_res,
                'defense_dragon': armor_binary.dragon_res,
                'skills': {},
                'craft': {}
            }

            # Add skills to new armor data
            for i in range(1, 2+1):
                skill_lvl = getattr(armor_binary, f"skill{i}_lvl")
                if skill_lvl != 0:
                    skill_id = getattr(armor_binary, f"skill{i}")
                    new_data['skills'][f'skill{i}_name'] = skill_map[skill_id]
                    new_data['skills'][f'skill{i}_pts'] = skill_lvl
                else:
                    new_data['skills'][f'skill{i}_name'] = None
                    new_data['skills'][f'skill{i}_pts'] = None

            # Add recipe to new armor data. Also track the encounter.
            recipe_binary = armor_craft_data[armor_binary.id]
            for i in range(1, 4+1):
                item_id = getattr(recipe_binary, f'item{i}_id')
                item_qty = getattr(recipe_binary, f'item{i}_qty')

                item_name = None
                if item_qty != 0:
                    item_name = item_text[item_id * 2]['en']
                    all_item_ids.add(item_id)

                new_data['craft'][f'item{i}_name'] = item_name
                new_data['craft'][f'item{i}_qty'] = item_qty if item_qty else None

            armor_entry = None
            if not existing_armor:
                print(f"Entry for {armor_name} not in armor map, creating new entry")
                armor_entry = new_armor_map.add_entry(next_armor_id, new_data)
                next_armor_id += 1

            else:
                armor_entry = new_armor_map.add_entry(existing_armor.id, {
                    **existing_armor,
                    **new_data
                })

    # Process set skills. As we don't currently understand the set -> skill map, we only translate
    for bonus_entry in mhdata.armorset_bonus_map.values():
        set_skill_idx = skill_map.reverse()[bonus_entry.name('en')]
        name_dict = skill_text[set_skill_idx * 3]
        new_armorset_bonus_map.insert({ **bonus_entry, 'name': name_dict })

    # Write new data
    writer.save_base_map_csv(
        "armors/armor_base.csv", 
        new_armor_map, 
        schema=schema.ArmorBaseSchema(),
        translation_filename="armors/armor_base_translations.csv")

    writer.save_data_csv(
        "armors/armor_skills_ext.csv",
        new_armor_map,
        key="skills"
    )

    writer.save_data_csv(
        "armors/armor_craft_ext.csv",
        new_armor_map,
        key="craft"
    )

    writer.save_base_map_csv(
        "armors/armorset_bonus_base.csv",
        new_armorset_bonus_map,
        schema=schema.ArmorSetBonus(),
        translation_filename="armors/armorset_bonus_base_translations.csv"
    )

    print("Armor files updated")

    add_missing_items(all_item_ids, mhdata=mhdata)

def add_missing_items(encountered_item_ids: Iterable[int], *, mhdata=None):
    if not mhdata:
        mhdata = load_data()
        print("Existing Data loaded. Using to expand item list")

    item_data = sorted(
        load_schema(ftypes.itm.Itm, "common/item/itemData.itm").entries,
        key=lambda i: i.order)
    item_text = load_text("common/text/steam/item")

    new_item_map = DataMap(languages='en')

    # First pass. Iterate over existing ingame items and merge with existing data
    for entry in item_data:
        name_dict = item_text[entry.id * 2]
        description_dict = item_text[entry.id * 2 + 1]
        existing_item = mhdata.item_map.entry_of('en', name_dict['en'])

        is_encountered = entry.id in encountered_item_ids
        if not is_encountered and not existing_item:
            continue

        # note: we omit buy price as items may have a buy price even if not sold.
        # We only care about the buy price of BUYABLE items
        new_data = {
            'name': name_dict,
            'description': description_dict,
            'rarity': entry.rarity + 1,
            'sell_price': entry.sell_price if entry.sell_price != 0 else None
        }

        is_ez = (entry.flags & itm.ItmFlag.IsQuestOnly.value) != 0
        is_account = item_type_list[entry.type] == 'endemic'
        is_tradein = "(Trade-in Item)" in description_dict['en']
        is_appraisal = (entry.flags & itm.ItmFlag.IsAppraisal.value) != 0
        
        if name_dict['en'] == 'Normal Ammo 1':
            new_data['category'] = 'hidden'
        elif is_ez:
            new_data['category'] = 'misc'
            new_data['subcategory'] = 'trade' if is_tradein else 'supply'
        elif is_account:
            new_data['category'] = 'misc'
            new_data['subcategory'] = 'trade' if is_tradein else 'account'
        elif is_appraisal:
            new_data['category'] = 'misc'
            new_data['subcategory'] = 'appraisal'
            new_data['sell_price'] = None  # why does this have values?
        else:
            new_data['category'] = item_type_list[entry.type]
            new_data['subcategory'] = 'trade' if is_tradein else None

            # Whether we show carry limit at all is based on item type.
            # Materials are basically infinite carry
            infinite_carry = new_data['category'] == 'material'
            new_data['carry_limit'] = None if infinite_carry else entry.carry_limit

        if existing_item:
            new_item_map.insert({ **existing_item, **new_data })
        else:
            new_item_map.insert(new_data)

    # Second pass, add old entries that are not in the new one
    for old_entry in mhdata.item_map.values():
        if old_entry.name('en') not in new_item_map.names('en'):
            new_item_map.insert(old_entry)


    # Third pass. Items need to be reordered based on type

    unsorted_item_map = new_item_map
    def filter_category(category, subcategory=None):
        "helper that returns items and then removes from unsorted item map"
        results = []
        for item in unsorted_item_map.values():
            if item['category'] == category and item['subcategory'] == subcategory:
                results.append(item)
        for result in results:
            del unsorted_item_map[result.id]
        return results

    normal_ammo_1 = unsorted_item_map.entry_of("en", "Normal Ammo 1")

    new_item_map = DataMap(languages="en")
    new_item_map.extend(filter_category('item'))
    new_item_map.extend(filter_category('material'))
    new_item_map.extend(filter_category('material', 'trade'))
    if normal_ammo_1:
        new_item_map.insert(normal_ammo_1)
    new_item_map.extend(filter_category('ammo'))
    new_item_map.extend(filter_category('misc', 'appraisal'))
    new_item_map.extend(filter_category('misc', 'account'))
    new_item_map.extend(filter_category('misc', 'supply'))

    # Write out data
    writer.save_base_map_csv(
        "items/item_base.csv",
        new_item_map,
        schema=schema.ItemSchema(),
        translation_filename="items/item_base_translations.csv",
        translation_extra=['description']
    )

    print("Item files updated")