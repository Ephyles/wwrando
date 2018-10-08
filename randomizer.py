
import os
from io import BytesIO
import shutil
from pathlib import Path
import re
from random import Random
from collections import OrderedDict
import hashlib
import yaml

from fs_helpers import *
from wwlib.yaz0_decomp import Yaz0Decompressor
from wwlib.rarc import RARC
from wwlib.rel import REL
from wwlib.gcm import GCM
from wwlib.jpc import JPC
import tweaks
from logic.logic import Logic
from paths import DATA_PATH, ASM_PATH, RANDO_ROOT_PATH
import customizer

from randomizers import items
from randomizers import charts
from randomizers import starting_island
from randomizers import dungeon_entrances

with open(os.path.join(RANDO_ROOT_PATH, "version.txt"), "r") as f:
  VERSION = f.read().strip()

VERSION_WITHOUT_COMMIT = VERSION

# Try to add the git commit hash to the version number if running from source.
try:
  from sys import _MEIPASS
except ImportError:
  git_commit_hash_file = os.path.join(RANDO_ROOT_PATH, ".git", "ORIG_HEAD")
  if os.path.isfile(git_commit_hash_file):
    with open(git_commit_hash_file, "r") as f:
      VERSION += "_" + f.read()[:7]

class TooFewProgressionLocationsError(Exception):
  pass

class Randomizer:
  def __init__(self, seed, clean_iso_path, randomized_output_folder, options, permalink=None, cmd_line_args=[]):
    self.randomized_output_folder = randomized_output_folder
    self.options = options
    self.seed = seed
    self.permalink = permalink
    
    self.dry_run = ("-dry" in cmd_line_args)
    self.disassemble = ("-disassemble" in cmd_line_args)
    self.export_disc_to_folder = ("-exportfolder" in cmd_line_args)
    self.no_logs = ("-nologs" in cmd_line_args)
    self.bulk_test = ("-bulk" in cmd_line_args)
    if self.bulk_test:
      self.dry_run = True
      self.no_logs = True
    
    self.integer_seed = self.convert_string_to_integer_md5(self.seed)
    self.rng = self.get_new_rng()
    
    self.arcs_by_path = {}
    self.jpcs_by_path = {}
    self.raw_files_by_path = {}
    
    if not self.dry_run:
      self.verify_supported_version(clean_iso_path)
      
      self.gcm = GCM(clean_iso_path)
      self.gcm.read_entire_disc()
      
      self.chart_list = self.get_arc("files/res/Msg/fmapres.arc").get_file("cmapdat.bin")
      self.bmg = self.get_arc("files/res/Msg/bmgres.arc").get_file("zel_00.bmg")
      
      if self.disassemble:
        self.disassemble_all_code()
    
    self.read_text_file_lists()
    
    # Starting items. This list is read by the Logic when initializing your currently owned items list.
    self.starting_items = [
      "Wind Waker",
      "Wind's Requiem",
      "Ballad of Gales",
      "Song of Passing",
      "Hero's Shield",
      "Boat's Sail",
    ]
    if self.options.get("sword_mode") == "Start with Sword":
      self.starting_items.append("Progressive Sword")
    # Add starting Triforce Shards.
    num_starting_triforce_shards = int(self.options.get("num_starting_triforce_shards", 0))
    for i in range(num_starting_triforce_shards):
      self.starting_items.append("Triforce Shard %d" % (i+1))
    
    # Default dungeon entrances to be used if dungeon entrance randomizer is not on.
    self.dungeon_entrances = OrderedDict([
      ("Dungeon Entrance On Dragon Roost Island", "Dragon Roost Cavern"),
      ("Dungeon Entrance In Forest Haven Sector", "Forbidden Woods"),
      ("Dungeon Entrance In Tower of the Gods Sector", "Tower of the Gods"),
      ("Dungeon Entrance On Headstone Island", "Earth Temple"),
      ("Dungeon Entrance On Gale Isle", "Wind Temple"),
    ])
    self.dungeon_island_locations = OrderedDict([
      ("Dragon Roost Cavern", "Dragon Roost Island"),
      ("Forbidden Woods", "Forest Haven"),
      ("Tower of the Gods", "Tower of the Gods"),
      ("Earth Temple", "Headstone Island"),
      ("Wind Temple", "Gale Isle"),
    ])
    
    # Default starting island (Outset) if the starting island randomizer is not on.
    self.starting_island_index = 44
    
    # Default charts for each island.
    self.island_number_to_chart_name = OrderedDict([
      (1, "Treasure Chart 25"),
      (2, "Treasure Chart 7"),
      (3, "Treasure Chart 24"),
      (4, "Triforce Chart 2"),
      (5, "Treasure Chart 11"),
      (6, "Triforce Chart 7"),
      (7, "Treasure Chart 13"),
      (8, "Treasure Chart 41"),
      (9, "Treasure Chart 29"),
      (10, "Treasure Chart 22"),
      (11, "Treasure Chart 18"),
      (12, "Treasure Chart 30"),
      (13, "Treasure Chart 39"),
      (14, "Treasure Chart 19"),
      (15, "Treasure Chart 8"),
      (16, "Treasure Chart 2"),
      (17, "Treasure Chart 10"),
      (18, "Treasure Chart 26"),
      (19, "Treasure Chart 3"),
      (20, "Treasure Chart 37"),
      (21, "Treasure Chart 27"),
      (22, "Treasure Chart 38"),
      (23, "Triforce Chart 1"),
      (24, "Treasure Chart 21"),
      (25, "Treasure Chart 6"),
      (26, "Treasure Chart 14"),
      (27, "Treasure Chart 34"),
      (28, "Treasure Chart 5"),
      (29, "Treasure Chart 28"),
      (30, "Treasure Chart 35"),
      (31, "Triforce Chart 3"),
      (32, "Triforce Chart 6"),
      (33, "Treasure Chart 1"),
      (34, "Treasure Chart 20"),
      (35, "Treasure Chart 36"),
      (36, "Treasure Chart 23"),
      (37, "Treasure Chart 12"),
      (38, "Treasure Chart 16"),
      (39, "Treasure Chart 4"),
      (40, "Treasure Chart 17"),
      (41, "Treasure Chart 31"),
      (42, "Triforce Chart 5"),
      (43, "Treasure Chart 9"),
      (44, "Triforce Chart 4"),
      (45, "Treasure Chart 40"),
      (46, "Triforce Chart 8"),
      (47, "Treasure Chart 15"),
      (48, "Treasure Chart 32"),
      (49, "Treasure Chart 33"),
    ])
    
    self.custom_model_name = "Link"
    
    self.logic = Logic(self)
    
    num_progress_locations = self.logic.get_num_progression_locations()
    num_progress_items = self.logic.get_num_progression_items()
    if num_progress_locations < num_progress_items: 
      error_message = "Not enough progress locations to place all progress items.\n\n"
      error_message += "Total progress items: %d\n" % num_progress_items
      error_message += "Progress locations with current options: %d\n\n" % num_progress_locations
      error_message += "You need to check more of the progress location options in order to give the randomizer enough space to place all the items."
      raise TooFewProgressionLocationsError(error_message)
    
    # We need to determine if the user's selected options result in a dungeons-only-start.
    # Dungeons-only-start meaning that the only locations accessible at the start of the run are dungeon locations.
    # e.g. If the user selects Dungeons, Expensive Purchases, and Sunken Treasures, the dungeon locations are the only ones the player can check first.
    # We need to distinguish this situation because it can cause issues for the randomizer's item placement logic.
    self.logic.temporarily_make_dungeon_entrance_macros_impossible()
    accessible_undone_locations = self.logic.get_accessible_remaining_locations(for_progression=True)
    if len(accessible_undone_locations) == 0:
      self.dungeons_only_start = True
    else:
      self.dungeons_only_start = False
    self.logic.update_dungeon_entrance_macros() # Reset the dungeon entrance macros.
  
  def randomize(self):
    options_completed = 0
    yield("Modifying game code...", options_completed)
    
    if not self.dry_run:
      self.apply_necessary_tweaks()
      
      if self.options.get("swift_sail"):
        tweaks.make_sail_behave_like_swift_sail(self)
      if self.options.get("instant_text_boxes"):
        tweaks.make_all_text_instant(self)
      if self.options.get("reveal_full_sea_chart"):
        tweaks.apply_patch(self, "reveal_sea_chart")
      if self.options.get("add_shortcut_warps_between_dungeons"):
        tweaks.add_inter_dungeon_warp_pots(self)
      if self.options.get("invert_camera_x_axis"):
        tweaks.apply_patch(self, "invert_camera_x_axis")
      tweaks.update_skip_rematch_bosses_game_variable(self)
      tweaks.update_sword_mode_game_variable(self)
      if self.options.get("sword_mode") == "Swordless":
        tweaks.apply_patch(self, "swordless")
        tweaks.update_text_for_swordless(self)
    
    options_completed += 1
    yield("Randomizing...", options_completed)
    
    if self.options.get("randomize_charts"):
      charts.randomize_charts(self)
    
    if self.options.get("randomize_starting_island"):
      starting_island.randomize_starting_island(self)
    
    if self.options.get("randomize_dungeon_entrances"):
      dungeon_entrances.randomize_dungeon_entrances(self)
    
    items.randomize_items(self)
    
    options_completed += 2
    yield("Saving items...", options_completed)
    
    if not self.dry_run:
      items.write_changed_items(self)
    
    if not self.dry_run:
      self.apply_necessary_post_randomization_tweaks()
    
    options_completed += 7
    yield("Saving randomized ISO...", options_completed)
    
    if not self.dry_run:
      self.save_randomized_iso()
    
    options_completed += 9
    yield("Writing logs...", options_completed)
    
    if self.options.get("generate_spoiler_log"):
      self.write_spoiler_log()
    self.write_non_spoiler_log()
    
    yield("Done", -1)
  
  def apply_necessary_tweaks(self):
    tweaks.apply_patch(self, "custom_funcs")
    tweaks.apply_patch(self, "necessary_fixes")
    tweaks.skip_wakeup_intro_and_start_at_dock(self)
    tweaks.start_ship_at_outset(self)
    tweaks.fix_deku_leaf_model(self)
    tweaks.allow_all_items_to_be_field_items(self)
    tweaks.remove_shop_item_forced_uniqueness_bit(self)
    tweaks.remove_forsaken_fortress_2_cutscenes(self)
    tweaks.make_items_progressive(self)
    tweaks.add_ganons_tower_warp_to_ff2(self)
    tweaks.add_chest_in_place_medli_grappling_hook_gift(self)
    tweaks.add_chest_in_place_queen_fairy_cutscene(self)
    #tweaks.add_cube_to_earth_temple_first_room(self)
    tweaks.add_more_magic_jars_to_dungeons(self)
    tweaks.remove_title_and_ending_videos(self)
    tweaks.modify_title_screen_logo(self)
    tweaks.update_game_name_icon_and_banners(self)
    tweaks.allow_dungeon_items_to_appear_anywhere(self)
    #tweaks.remove_ballad_of_gales_warp_in_cutscene(self)
    tweaks.fix_shop_item_y_offsets(self)
    tweaks.shorten_zephos_event(self)
    tweaks.update_korl_dialogue(self)
    tweaks.set_num_starting_triforce_shards(self)
    tweaks.add_pirate_ship_to_windfall(self)
    tweaks.remove_makar_kidnapping_event(self)
    tweaks.increase_player_movement_speeds(self)
    tweaks.add_chart_number_to_item_get_messages(self)
    tweaks.shorten_auction_intro_event(self)
    tweaks.disable_invisible_walls(self)
    tweaks.add_hint_signs(self)
    tweaks.prevent_door_boulder_softlocks(self)
    tweaks.update_tingle_statue_item_get_funcs(self)
    tweaks.apply_patch(self, "tingle_chests_without_tuner")
    tweaks.make_tingle_statue_reward_rupee_rainbow_colored(self)
    tweaks.show_seed_hash_on_name_entry_screen(self)
    
    customizer.replace_link_model(self)
    tweaks.change_starting_clothes(self)
    customizer.change_player_clothes_color(self)
  
  def apply_necessary_post_randomization_tweaks(self):
    tweaks.update_shop_item_descriptions(self)
    tweaks.update_auction_item_names(self)
    tweaks.update_sinking_ships_item_names(self)
    tweaks.update_item_names_in_letter_advertising_rock_spire_shop(self)
    tweaks.update_savage_labyrinth_hint_tablet(self)
    tweaks.update_fishmen_hints(self)
  
  def verify_supported_version(self, clean_iso_path):
    if not os.path.isfile(clean_iso_path):
      raise Exception("Clean WW ISO does not exist: %s" % clean_iso_path)
    
    with open(clean_iso_path, "rb") as f:
      game_id = try_read_str(f, 0, 6)
    if game_id != "GZLE01":
      if game_id and game_id.startswith("GZL"):
        raise Exception("Invalid version of Wind Waker. Only the USA version is supported by this randomizer.")
      else:
        raise Exception("Invalid game given as the clean ISO. You must specify a Wind Waker ISO (USA version).")
  
  def read_text_file_lists(self):
    # Get item names.
    self.item_names = {}
    self.item_name_to_id = {}
    with open(os.path.join(DATA_PATH, "item_names.txt"), "r") as f:
      matches = re.findall(r"^([0-9a-f]{2}) - (.+)$", f.read(), re.IGNORECASE | re.MULTILINE)
    for item_id, item_name in matches:
      if item_name:
        item_id = int(item_id, 16)
        self.item_names[item_id] = item_name
        if item_name in self.item_name_to_id:
          raise Exception("Duplicate item name: " + item_name)
        self.item_name_to_id[item_name] = item_id
    
    # Get stage and island names for debug purposes.
    self.stage_names = {}
    with open(os.path.join(DATA_PATH, "stage_names.txt"), "r") as f:
      while True:
        stage_folder = f.readline()
        if not stage_folder:
          break
        stage_name = f.readline()
        self.stage_names[stage_folder.strip()] = stage_name.strip()
    self.island_names = {}
    self.island_number_to_name = {}
    with open(os.path.join(DATA_PATH, "island_names.txt"), "r") as f:
      while True:
        room_arc_name = f.readline()
        if not room_arc_name:
          break
        island_name = f.readline().strip()
        self.island_names[room_arc_name.strip()] = island_name
        island_number = int(re.search(r"Room(\d+)", room_arc_name).group(1))
        self.island_number_to_name[island_number] = island_name
    
    self.item_ids_without_a_field_model = []
    with open(os.path.join(DATA_PATH, "items_without_field_models.txt"), "r") as f:
      matches = re.findall(r"^([0-9a-f]{2}) ", f.read(), re.IGNORECASE | re.MULTILINE)
    for item_id in matches:
      if item_name:
        item_id = int(item_id, 16)
        self.item_ids_without_a_field_model.append(item_id)
    
    self.arc_name_pointers = {}
    with open(os.path.join(DATA_PATH, "item_resource_arc_name_pointers.txt"), "r") as f:
      matches = re.findall(r"^([0-9a-f]{2}) ([0-9a-f]{8}) ", f.read(), re.IGNORECASE | re.MULTILINE)
    for item_id, arc_name_pointer in matches:
      item_id = int(item_id, 16)
      arc_name_pointer = int(arc_name_pointer, 16)
      self.arc_name_pointers[item_id] = arc_name_pointer
    
    self.icon_name_pointer = {}
    with open(os.path.join(DATA_PATH, "item_resource_icon_name_pointers.txt"), "r") as f:
      matches = re.findall(r"^([0-9a-f]{2}) ([0-9a-f]{8}) ", f.read(), re.IGNORECASE | re.MULTILINE)
    for item_id, icon_name_pointer in matches:
      item_id = int(item_id, 16)
      icon_name_pointer = int(icon_name_pointer, 16)
      self.icon_name_pointer[item_id] = icon_name_pointer
    
    self.custom_symbols = {}
    with open(os.path.join(ASM_PATH, "custom_symbols.txt"), "r") as f:
      matches = re.findall(r"^([0-9a-f]{8}) (\S+)", f.read(), re.IGNORECASE | re.MULTILINE)
    for symbol_address, symbol_name in matches:
      self.custom_symbols[symbol_name] = int(symbol_address, 16)
    
    with open(os.path.join(DATA_PATH, "progress_item_hints.txt"), "r") as f:
      self.progress_item_hints = yaml.load(f)
    
    with open(os.path.join(DATA_PATH, "island_name_hints.txt"), "r") as f:
      self.island_name_hints = yaml.load(f)
  
  def get_arc(self, arc_path):
    arc_path = arc_path.replace("\\", "/")
    
    if arc_path in self.arcs_by_path:
      return self.arcs_by_path[arc_path]
    else:
      data = self.gcm.read_file_data(arc_path)
      arc = RARC(data)
      self.arcs_by_path[arc_path] = arc
      return arc
  
  def get_jpc(self, jpc_path):
    jpc_path = jpc_path.replace("\\", "/")
    
    if jpc_path in self.jpcs_by_path:
      return self.jpcs_by_path[jpc_path]
    else:
      data = self.gcm.read_file_data(jpc_path)
      jpc = JPC(data)
      self.jpcs_by_path[jpc_path] = jpc
      return jpc
  
  def get_raw_file(self, file_path):
    file_path = file_path.replace("\\", "/")
    
    if file_path in self.raw_files_by_path:
      return self.raw_files_by_path[file_path]
    else:
      if file_path.startswith("files/rels/"):
        rel_name = os.path.basename(file_path)
        rels_arc = self.get_arc("files/RELS.arc")
        rel_file_entry = rels_arc.get_file_entry(rel_name)
      else:
        rel_file_entry = None
      
      if rel_file_entry:
        rel_file_entry.decompress_data_if_necessary()
        data = rel_file_entry.data
      else:
        data = self.gcm.read_file_data(file_path)
      
      if try_read_str(data, 0, 4) == "Yaz0":
        data = Yaz0Decompressor.decompress(data)
      
      self.raw_files_by_path[file_path] = data
      return data
  
  def replace_arc(self, arc_path, new_data):
    if arc_path not in self.gcm.files_by_path:
      raise Exception("Cannot replace RARC that doesn't exist: " + arc_path)
    
    arc = RARC(new_data)
    self.arcs_by_path[arc_path] = arc
  
  def replace_raw_file(self, file_path, new_data):
    if file_path not in self.gcm.files_by_path:
      raise Exception("Cannot replace file that doesn't exist: " + file_path)
    
    self.raw_files_by_path[file_path] = new_data
  
  def save_randomized_iso(self):
    self.bmg.save_changes()
    
    changed_files = {}
    for file_path, data in self.raw_files_by_path.items():
      if file_path.startswith("files/rels/"):
        rel_name = os.path.basename(file_path)
        rels_arc = self.get_arc("files/RELS.arc")
        rel_file_entry = rels_arc.get_file_entry(rel_name)
        if rel_file_entry:
          # Modify the RELS.arc entry for this rel.
          rel_file_entry.data = data
          continue
      
      changed_files[file_path] = data
    for arc_path, arc in self.arcs_by_path.items():
      for file_name, instantiated_file in arc.instantiated_object_files.items():
        if file_name == "event_list.dat":
          instantiated_file.save_changes()
      
      arc.save_changes()
      changed_files[arc_path] = arc.data
    for jpc_path, jpc in self.jpcs_by_path.items():
      jpc.save_changes()
      changed_files[jpc_path] = jpc.data
    
    if self.export_disc_to_folder:
      output_folder_path = os.path.join(self.randomized_output_folder, "WW Random %s" % self.seed)
      self.gcm.export_disc_to_folder_with_changed_files(output_folder_path, changed_files)
    else:
      output_file_path = os.path.join(self.randomized_output_folder, "WW Random %s.iso" % self.seed)
      self.gcm.export_disc_to_iso_with_changed_files(output_file_path, changed_files)
  
  def convert_string_to_integer_md5(self, string):
    return int(hashlib.md5(string.encode('utf-8')).hexdigest(), 16)
  
  def get_new_rng(self):
    rng = Random()
    rng.seed(self.integer_seed)
    if not self.options.get("generate_spoiler_log"):
      for i in range(1, 100):
        rng.getrandbits(i)
    return rng
  
  def each_stage_and_room(self, exclude_stages=False, exclude_rooms=False):
    all_filenames = list(self.gcm.files_by_path.keys())
    
    # Sort the file names for determinism. And use natural sorting so the room numbers are in order.
    try_int_convert = lambda string: int(string) if string.isdigit() else string
    all_filenames.sort(key=lambda filename: [try_int_convert(c) for c in re.split("([0-9]+)", filename)])
    
    all_stage_arc_paths = []
    all_room_arc_paths = []
    for filename in all_filenames:
      stage_match = re.search(r"files/res/Stage/([^/]+)/Stage.arc", filename, re.IGNORECASE)
      room_match = re.search(r"files/res/Stage/([^/]+)/Room\d+.arc", filename, re.IGNORECASE)
      
      if stage_match and exclude_stages:
        continue
      if room_match and exclude_rooms:
        continue
      
      if stage_match:
        stage_name = stage_match.group(1)
        if self.stage_names[stage_name] == "Unused":
          # Don't iterate through unused stages. Not only would they be useless, but some unused stages have slightly different stage formats that the rando can't read.
          continue
        all_stage_arc_paths.append(filename)
      
      if room_match:
        stage_name = room_match.group(1)
        if self.stage_names[stage_name] == "Unused":
          # Don't iterate through unused stages. Not only would they be useless, but some unused stages have slightly different stage formats that the rando can't read.
          continue
        all_room_arc_paths.append(filename)
    
    for stage_arc_path in all_stage_arc_paths:
      dzs = self.get_arc(stage_arc_path).get_file("stage.dzs")
      if dzs is None:
        continue
      yield(dzs, stage_arc_path)
    for room_arc_path in all_room_arc_paths:
      dzr = self.get_arc(room_arc_path).get_file("room.dzr")
      if dzr is None:
        continue
      yield(dzr, room_arc_path)
  
  def each_stage(self):
    return self.each_stage_and_room(exclude_rooms=True)
  
  def each_room(self):
    return self.each_stage_and_room(exclude_stages=True)
  
  def calculate_playthrough_progression_spheres(self):
    progression_spheres = []
    
    logic = Logic(self)
    previously_accessible_locations = []
    game_beatable = False
    while logic.unplaced_progress_items:
      progress_items_in_this_sphere = OrderedDict()
      
      accessible_locations = logic.get_accessible_remaining_locations()
      locations_in_this_sphere = [
        loc for loc in accessible_locations
        if loc not in previously_accessible_locations
      ]
      if not locations_in_this_sphere:
        raise Exception("Failed to calculate progression spheres")
      
      
      if not self.options.get("keylunacy"):
        # If the player gained access to any small keys, we need to give them the keys without counting that as a new sphere.
        newly_accessible_dungeon_item_locations = [
          loc for loc in locations_in_this_sphere
          if loc in self.logic.prerandomization_dungeon_item_locations
        ]
        newly_accessible_small_key_locations = [
          loc for loc in newly_accessible_dungeon_item_locations
          if self.logic.prerandomization_dungeon_item_locations[loc].endswith(" Small Key")
        ]
        if newly_accessible_small_key_locations:
          for small_key_location_name in newly_accessible_small_key_locations:
            item_name = self.logic.prerandomization_dungeon_item_locations[small_key_location_name]
            assert item_name.endswith(" Small Key")
            
            logic.add_owned_item(item_name)
          
          previously_accessible_locations += newly_accessible_small_key_locations
          continue # Redo this loop iteration with the small key locations no longer being considered 'remaining'.
      
      
      for location_name in locations_in_this_sphere:
        item_name = self.logic.done_item_locations[location_name]
        if item_name in logic.all_progress_items:
          progress_items_in_this_sphere[location_name] = item_name
      
      if not game_beatable:
        game_beatable = logic.check_requirement_met("Can Reach and Defeat Ganondorf")
        if game_beatable:
          progress_items_in_this_sphere["Ganon's Tower - Rooftop"] = "Defeat Ganondorf"
      
      progression_spheres.append(progress_items_in_this_sphere)
      
      for location_name, item_name in progress_items_in_this_sphere.items():
        if item_name == "Defeat Ganondorf":
          continue
        logic.add_owned_item(item_name)
      for group_name, item_names in logic.progress_item_groups.items():
        entire_group_is_owned = all(item_name in logic.currently_owned_items for item_name in item_names)
        if entire_group_is_owned and group_name in logic.unplaced_progress_items:
          logic.unplaced_progress_items.remove(group_name)
      
      previously_accessible_locations = accessible_locations
    
    if not game_beatable:
      # If the game wasn't already beatable on a previous progression sphere but it is now we add one final one just for this.
      game_beatable = logic.check_requirement_met("Can Reach and Defeat Ganondorf")
      if game_beatable:
        final_progression_sphere = OrderedDict([
          ("Ganon's Tower - Rooftop", "Defeat Ganondorf"),
        ])
        progression_spheres.append(final_progression_sphere)
    
    return progression_spheres
  
  def get_log_header(self):
    header = ""
    
    header += "Wind Waker Randomizer Version %s\n" % VERSION
    
    if self.permalink:
      header += "Permalink: %s\n" % self.permalink
    
    header += "Seed: %s\n" % self.seed
    
    header += "Options selected:\n  "
    non_disabled_options = [name for name in self.options if self.options[name] != False]
    option_strings = []
    for option_name in non_disabled_options:
      if isinstance(self.options[option_name], bool):
        option_strings.append(option_name)
      else:
        option_strings.append("%s: %s" % (option_name, self.options[option_name]))
    header += ", ".join(option_strings)
    header += "\n\n\n"
    
    return header
  
  def get_zones_and_max_location_name_len(self, locations):
    zones = OrderedDict()
    max_location_name_length = 0
    for location_name in locations:
      zone_name, specific_location_name = self.logic.split_location_name_by_zone(location_name)
      
      if zone_name not in zones:
        zones[zone_name] = []
      zones[zone_name].append((location_name, specific_location_name))
      
      if len(specific_location_name) > max_location_name_length:
        max_location_name_length = len(specific_location_name)
    
    return (zones, max_location_name_length)
  
  def write_non_spoiler_log(self):
    if self.no_logs:
      return
    
    log_str = self.get_log_header()
    
    progress_locations, nonprogress_locations = self.logic.get_progress_and_non_progress_locations()
    
    zones, max_location_name_length = self.get_zones_and_max_location_name_len(self.logic.done_item_locations)
    format_string = "    %s\n"
    
    # Write progress item locations.
    log_str += "### Locations that may or may not have progress items in them on this run:\n"
    for zone_name, locations_in_zone in zones.items():
      if not any(loc for (loc, _) in locations_in_zone if loc in progress_locations):
        # No progress locations for this zone.
        continue
      
      log_str += zone_name + ":\n"
      
      for (location_name, specific_location_name) in locations_in_zone:
        if location_name in progress_locations:
          item_name = self.logic.done_item_locations[location_name]
          log_str += format_string % specific_location_name
    
    log_str += "\n\n"
    
    
    # Write nonprogress item locations.
    log_str += "### Locations that cannot have progress items in them on this run:\n"
    for zone_name, locations_in_zone in zones.items():
      if not any(loc for (loc, _) in locations_in_zone if loc in nonprogress_locations):
        # No nonprogress locations for this zone.
        continue
      
      log_str += zone_name + ":\n"
      
      for (location_name, specific_location_name) in locations_in_zone:
        if location_name in nonprogress_locations:
          item_name = self.logic.done_item_locations[location_name]
          log_str += format_string % specific_location_name
    
    nonspoiler_log_output_path = os.path.join(self.randomized_output_folder, "WW Random %s - Non-Spoiler Log.txt" % self.seed)
    with open(nonspoiler_log_output_path, "w") as f:
      f.write(log_str)
  
  def write_spoiler_log(self):
    if self.no_logs:
      return
    
    spoiler_log = self.get_log_header()
    
    # Write progression spheres.
    spoiler_log += "Playthrough:\n"
    progression_spheres = self.calculate_playthrough_progression_spheres()
    all_progression_sphere_locations = [loc for locs in progression_spheres for loc in locs]
    zones, max_location_name_length = self.get_zones_and_max_location_name_len(all_progression_sphere_locations)
    format_string = "      %-" + str(max_location_name_length+1) + "s %s\n"
    for i, progression_sphere in enumerate(progression_spheres):
      spoiler_log += "%d:\n" % (i+1)
      
      for zone_name, locations_in_zone in zones.items():
        if not any(loc for (loc, _) in locations_in_zone if loc in progression_sphere):
          # No locations in this zone are used in this sphere.
          continue
        
        spoiler_log += "  %s:\n" % zone_name
        
        for (location_name, specific_location_name) in locations_in_zone:
          if location_name in progression_sphere:
            if location_name == "Ganon's Tower - Rooftop":
              item_name = "Defeat Ganondorf"
            else:
              item_name = self.logic.done_item_locations[location_name]
            spoiler_log += format_string % (specific_location_name + ":", item_name)
      
    spoiler_log += "\n\n\n"
    
    # Write item locations.
    spoiler_log += "All item locations:\n"
    zones, max_location_name_length = self.get_zones_and_max_location_name_len(self.logic.done_item_locations)
    format_string = "    %-" + str(max_location_name_length+1) + "s %s\n"
    for zone_name, locations_in_zone in zones.items():
      spoiler_log += zone_name + ":\n"
      
      for (location_name, specific_location_name) in locations_in_zone:
        item_name = self.logic.done_item_locations[location_name]
        spoiler_log += format_string % (specific_location_name + ":", item_name)
    
    spoiler_log += "\n\n\n"
    
    # Write starting island.
    spoiler_log += "Starting island: "
    spoiler_log += self.island_number_to_name[self.starting_island_index]
    spoiler_log += "\n"
    
    spoiler_log += "\n\n\n"
    
    # Write dungeon entrances.
    spoiler_log += "Dungeon entrances:\n"
    for entrance_name, dungeon_name in self.dungeon_entrances.items():
      spoiler_log += "  %-45s %s\n" % (entrance_name+":", dungeon_name)
    
    spoiler_log += "\n\n\n"
    
    # Write treasure charts.
    spoiler_log += "Charts:\n"
    chart_name_to_island_number = {}
    for island_number in range(1, 49+1):
      chart_name = self.logic.macros["Chart for Island %d" % island_number][0]
      chart_name_to_island_number[chart_name] = island_number
    for chart_number in range(1, 49+1):
      if chart_number <= 8:
        chart_name = "Triforce Chart %d" % chart_number
      else:
        chart_name = "Treasure Chart %d" % (chart_number-8)
      island_number = chart_name_to_island_number[chart_name]
      island_name = self.island_number_to_name[island_number]
      spoiler_log += "  %-18s %s\n" % (chart_name+":", island_name)
    
    spoiler_log_output_path = os.path.join(self.randomized_output_folder, "WW Random %s - Spoiler Log.txt" % self.seed)
    with open(spoiler_log_output_path, "w") as f:
      f.write(spoiler_log)
  
  def write_error_log(self, error_message):
    if self.no_logs:
      return
    
    error_log_str = self.get_log_header()
    
    error_log_str += error_message
    
    error_log_output_path = os.path.join(self.randomized_output_folder, "WW Random %s - Error Log.txt" % self.seed)
    with open(error_log_output_path, "w") as f:
      f.write(error_log_str)
  
  def disassemble_all_code(self):
    from asm.disassemble import disassemble_all_code
    disassemble_all_code(self)
