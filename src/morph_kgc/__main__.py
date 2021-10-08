__author__ = "Julián Arenas-Guerrero"
__credits__ = ["Julián Arenas-Guerrero"]

__license__ = "Apache-2.0"
__maintainer__ = "Julián Arenas-Guerrero"
__email__ = "arenas.guerrero.julian@outlook.com"


from .args_parser import load_config_from_command_line
from .engine import retrieve_mappings, process_materialization


if __name__ == "__main__":

    config = load_config_from_command_line()

    mappings = retrieve_mappings(config)
    process_materialization(mappings, config)
