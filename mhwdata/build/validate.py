import itertools

from mhwdata.io import DataMap
from mhwdata.util import ensure_warn

# todo: inject data instead once we figure out how we're gonna pass it around
from mhwdata.load import *

def validate():
    "Perform all validations, print out the errors, and return if it succeeded or not"
    errors = []
    errors.extend(validate_monster_props())
    errors.extend(validate_monster_weaknesses())
    errors.extend(validate_monster_rewards())

    if errors:
        for error in errors:
            print("ERROR: " + error)
        return False

    return True

def validate_monster_props():
    errors = []
    for entry in monster_map.values():
        ensure_warn('hitzones' in entry, f"Monster {entry.name('en')} missing hitzones")
    
    return errors

def validate_monster_weaknesses():
    "Checks for valid data intelligence. The only fatal is a missing normal state"
    errors = []
    
    for entry in monster_map.values():
        if entry['size'] == 'small':
            continue

        name = entry.name('en')

        if 'weaknesses' not in entry:
            print(f"Warning: Large monster {name} does not contain a weakness entry")
            continue

        if 'normal' not in entry['weaknesses']:
            errors.append(f"Invalid weaknesses in {name}, normal is a required state")

    return errors

def validate_monster_rewards():
    """Validates monster rewards for sane values. 
    Certain fields (like carve) sum to 100, 
    Others (like quest rewards) must be at least 100%"""

    # Those other than these are validated for 100% drop rate EXACT.
    # Quest rewards sometimes contain a guaranteed reward.
    # We should probably separate, but most databases don't separate them.
    # Investigate further
    uncapped_conditions = ("Quest Reward / Investigation (Bronze)")

    errors = set()
    
    for monster_id, entry in monster_map.items():
        if 'rewards' not in entry:
            continue

        monster_name = entry.name('en') # used for error display

        # accumulates percentages by rank
        reward_percentages = { rank:[] for rank in supported_ranks }

        valid = True
        for reward in entry['rewards']:
            condition = reward['condition_en']
            rank = reward['rank']

            # ensure condition exists
            if condition not in monster_reward_conditions_map.names('en'):
                errors.add(f"Invalid condition {condition} in monster {monster_name}")
                valid = False

            if rank not in supported_ranks:
                errors.add(f"Unsupported rank {rank} in {monster_name} rewards")
                valid = False

        if not valid:
            continue
        
        # Ensure percentage is correct (at or greater than 100)
        rank_reward_key_fn = lambda r: (r['rank'], r['condition_en'])
        sorted_rewards = sorted(entry['rewards'], key=rank_reward_key_fn)
        for (rank, condition), items in itertools.groupby(sorted_rewards, rank_reward_key_fn):
            percentage_sum = sum((int(r['percentage']) for r in items), 0)

            key_str = f"(rank {rank} condition {condition})"
            error_start = f"Rewards %'s for monster {monster_name} {key_str}"
            if condition not in uncapped_conditions:
                ensure_warn(
                    percentage_sum == 100, 
                    f"{error_start} does not sum to 100")
            else:
                ensure_warn(
                    percentage_sum >= 100, 
                    f"{error_start} does not sum to at least 100")

    return errors
