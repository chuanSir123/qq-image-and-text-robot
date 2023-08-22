# my_map.py

my_global_map = {}

def add_to_map(key, value):
    my_global_map[key] = value

def get_from_map(key):
    return my_global_map.get(key)
