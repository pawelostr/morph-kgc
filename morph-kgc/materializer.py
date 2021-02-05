""" Morph-KGC """

__author__ = "Julián Arenas-Guerrero"
__copyright__ = "Copyright (C) 2020 Julián Arenas-Guerrero"
__credits__ = ["Julián Arenas-Guerrero"]

__license__ = "Apache-2.0"
__maintainer__ = "Julián Arenas-Guerrero"
__email__ = "arenas.guerrero.julian@outlook.com"


import logging
import time

from urllib.parse import quote

from data_sources import relational_source
import utils


def _get_references_in_mapping_rule(mapping_rule, only_subject_map=False):
    references = []
    if mapping_rule['subject_template']:
        references.extend(utils.get_references_in_template(str(mapping_rule['subject_template'])))
    elif mapping_rule['subject_reference']:
        references.append(str(mapping_rule['subject_reference']))

    if not only_subject_map:
        if mapping_rule['predicate_template']:
            references.extend(utils.get_references_in_template(str(mapping_rule['predicate_template'])))
        elif mapping_rule['predicate_reference']:
            references.append(str(mapping_rule['predicate_reference']))
        if mapping_rule['object_template']:
            references.extend(utils.get_references_in_template(str(mapping_rule['object_template'])))
        elif mapping_rule['object_reference']:
            references.append(str(mapping_rule['object_reference']))

    return set(references)


def _materialize_template(query_results_df, template, columns_alias='', termtype='http://www.w3.org/ns/r2rml#IRI', language_tag='', datatype=''):
    references = utils.get_references_in_template(str(template))

    if str(termtype).strip() == 'http://www.w3.org/ns/r2rml#Literal':
        query_results_df['triple'] = query_results_df['triple'] + '"'
    else:
        query_results_df['triple'] = query_results_df['triple'] + '<'

    for reference in references:
        query_results_df['reference_results'] = query_results_df[columns_alias + reference]

        if str(termtype).strip() == 'http://www.w3.org/ns/r2rml#IRI':
            query_results_df['reference_results'] = query_results_df['reference_results'].apply(lambda x: quote(x))

        splitted_template = template.split('{' + reference + '}')
        query_results_df['triple'] = query_results_df['triple'] + splitted_template[0]
        query_results_df['triple'] = query_results_df['triple'] + query_results_df['reference_results']
        template = str('{' + reference + '}').join(splitted_template[1:])

    if str(termtype).strip() == 'http://www.w3.org/ns/r2rml#Literal':
        query_results_df['triple'] = query_results_df['triple'] + '"'
        if language_tag:
            query_results_df['triple'] = query_results_df['triple'] + '@' + language_tag + ' '
        elif datatype:
            query_results_df['triple'] = query_results_df['triple'] + '^^<' + datatype + '> '
        else:
            query_results_df['triple'] = query_results_df['triple'] + ' '
    else:
        query_results_df['triple'] = query_results_df['triple'] + '> '

    return query_results_df


def _materialize_reference(query_results_df, reference, columns_alias='', termtype='http://www.w3.org/ns/r2rml#Literal', language_tag='', datatype=''):
    query_results_df['reference_results'] = query_results_df[columns_alias + str(reference)]

    if str(termtype).strip() == 'http://www.w3.org/ns/r2rml#IRI':
        query_results_df['reference_results'] = query_results_df['reference_results'].apply(lambda x: quote(x, safe='://'))
        query_results_df['triple'] = query_results_df['triple'] + '<' + query_results_df['reference_results'] + '> '
    elif str(termtype).strip() == 'http://www.w3.org/ns/r2rml#Literal':
        query_results_df['triple'] = query_results_df['triple'] + '"' + query_results_df['reference_results'] + '"'
        if language_tag:
            query_results_df['triple'] = query_results_df['triple'] + '@' + language_tag + ' '
        elif datatype:
            query_results_df['triple'] = query_results_df['triple'] + '^^<' + datatype + '> '
        else:
            query_results_df['triple'] = query_results_df['triple'] + ' '

    return query_results_df


def _materialize_constant(query_results_df, constant, termtype='http://www.w3.org/ns/r2rml#IRI', language_tag='', datatype=''):
    if str(termtype).strip() == 'http://www.w3.org/ns/r2rml#Literal':
        complete_constant = '"' + constant + '"'

        if language_tag:
            complete_constant = complete_constant + '@' + language_tag + ' '
        elif datatype:
            complete_constant = complete_constant + '^^<' + datatype + '> '
        else:
            complete_constant = complete_constant + ' '
    else:
        complete_constant = '<' + str(constant) + '> '

    query_results_df['triple'] = query_results_df['triple'] + complete_constant

    return query_results_df


def _materialize_mapping_rule(mapping_rule, subject_maps_df, config):
    query = 'SELECT '
    if config.getboolean('CONFIGURATION', 'push_down_sql_distincts'):
        query = query + 'DISTINCT '

    if mapping_rule['object_parent_triples_map']:
        child_references = _get_references_in_mapping_rule(mapping_rule)

        parent_triples_map_rule = \
            subject_maps_df[subject_maps_df.triples_map_id==mapping_rule['object_parent_triples_map']].iloc[0]
        parent_references = _get_references_in_mapping_rule(parent_triples_map_rule, only_subject_map=True)

        for key, join_condition in eval(mapping_rule['join_conditions']).items():
            parent_references.add(join_condition['parent_value'])
            child_references.add(join_condition['child_value'])

        child_query = 'SELECT '
        if len(child_references) > 0:
            for reference in child_references:
                child_query = child_query + reference + ' AS child_' + reference + ', '
            child_query = child_query[:-2] + ' FROM ' + mapping_rule['tablename'] + ' WHERE '
            for reference in child_references:
                child_query = child_query + reference + ' IS NOT NULL AND '
            child_query = child_query[:-5]
        else:
            child_query = None

        parent_query = 'SELECT '
        if len(parent_references) > 0:
            for reference in parent_references:
                parent_query = parent_query + reference + ' AS parent_' + reference + ', '
            parent_query = parent_query[:-2] + ' FROM ' + parent_triples_map_rule['tablename'] + ' WHERE '
            for reference in parent_references:
                parent_query = parent_query + reference + ' IS NOT NULL AND '
            parent_query = parent_query[:-5]
        else:
            parent_query = None

        query = query + '* FROM (' + child_query + ') AS child, (' + parent_query + ') AS parent WHERE '
        for key, join_condition in eval(mapping_rule['join_conditions']).items():
            query = query + 'child.child_' + join_condition['child_value'] + \
                    '=parent.parent_' + join_condition['parent_value'] + ' AND '
        query = query[:-4] + ';'

        query_results_df = relational_source.execute_relational_query(query, config, mapping_rule['source_name'])

        query_results_df['triple'] = ''
        if mapping_rule['subject_template']:
            query_results_df = _materialize_template(
                query_results_df, mapping_rule['subject_template'], termtype=mapping_rule['subject_termtype'], columns_alias='child_')
        elif mapping_rule['subject_constant']:
            query_results_df = _materialize_constant(query_results_df, mapping_rule['subject_constant'], termtype=mapping_rule['subject_termtype'])
        elif mapping_rule['subject_reference']:
            query_results_df = _materialize_reference(
                query_results_df, mapping_rule['subject_reference'], termtype=mapping_rule['subject_termtype'], columns_alias='child_')
        if mapping_rule['predicate_template']:
            query_results_df = _materialize_template(
                query_results_df, mapping_rule['predicate_template'], columns_alias='child_')
        elif mapping_rule['predicate_constant']:
            query_results_df = _materialize_constant(query_results_df, mapping_rule['predicate_constant'])
        elif mapping_rule['predicate_reference']:
            query_results_df = _materialize_reference(
                query_results_df, mapping_rule['predicate_reference'], columns_alias='child_')
        if parent_triples_map_rule['subject_template']:
            query_results_df = _materialize_template(
                query_results_df, parent_triples_map_rule['subject_template'], termtype=parent_triples_map_rule['subject_termtype'], columns_alias='parent_')
        elif parent_triples_map_rule['subject_constant']:
            query_results_df = _materialize_constant(query_results_df, parent_triples_map_rule['subject_constant'], termtype=parent_triples_map_rule['subject_termtype'])
        elif parent_triples_map_rule['subject_reference']:
            query_results_df = _materialize_reference(
                query_results_df, parent_triples_map_rule['subject_reference'], termtype=parent_triples_map_rule['subject_termtype'], columns_alias='parent_')

    else:
        references = _get_references_in_mapping_rule(mapping_rule)

        if len(references) > 0:
            for reference in references:
                query = query + reference + ', '
            query = query[:-2] + ' FROM ' + mapping_rule['tablename'] + ' WHERE '
            for reference in references:
                query = query + reference + ' IS NOT NULL AND '
            query = query[:-4] + ';'
        else:
            query = None

        query_results_df = relational_source.execute_relational_query(query, config, mapping_rule['source_name'])

        query_results_df['triple'] = ''
        if mapping_rule['subject_template']:
            query_results_df = _materialize_template(query_results_df, mapping_rule['subject_template'], termtype=mapping_rule['subject_termtype'])
        elif mapping_rule['subject_constant']:
            query_results_df = _materialize_constant(query_results_df, mapping_rule['subject_constant'], termtype=mapping_rule['subject_termtype'])
        elif mapping_rule['subject_reference']:
            query_results_df = _materialize_reference(query_results_df, mapping_rule['subject_reference'], termtype=mapping_rule['subject_termtype'])
        if mapping_rule['predicate_template']:
            query_results_df = _materialize_template(query_results_df, mapping_rule['predicate_template'])
        elif mapping_rule['predicate_constant']:
            query_results_df = _materialize_constant(query_results_df, mapping_rule['predicate_constant'])
        elif mapping_rule['predicate_reference']:
            query_results_df = _materialize_reference(query_results_df, mapping_rule['predicate_reference'])
        if mapping_rule['object_template']:
            query_results_df = _materialize_template(query_results_df, mapping_rule['object_template'], termtype=mapping_rule['object_termtype'], language_tag=mapping_rule['object_language'], datatype=mapping_rule['object_datatype'])
        elif mapping_rule['object_constant']:
            query_results_df = _materialize_constant(query_results_df, mapping_rule['object_constant'], termtype=mapping_rule['object_termtype'], language_tag=mapping_rule['object_language'], datatype=mapping_rule['object_datatype'])
        elif mapping_rule['object_reference']:
            query_results_df = _materialize_reference(query_results_df, mapping_rule['object_reference'], termtype=mapping_rule['object_termtype'], language_tag=mapping_rule['object_language'], datatype=mapping_rule['object_datatype'])

    return query_results_df['triple']


def materialize(mappings_df, config):
    subject_maps_df = utils.get_subject_maps(mappings_df)
    mapping_partitions = [group for _, group in mappings_df.groupby(by='mapping_partition')]

    utils.prepare_output_dir(config, len(mapping_partitions))

    for mapping_partition in mapping_partitions:
        triples = set()
        for i, mapping_rule in mapping_partition.iterrows():
            triples.update(set(_materialize_mapping_rule(mapping_rule, subject_maps_df, config)))
        utils.triples_to_file(triples, config, mapping_partition.iloc[0]['mapping_partition'])

    if len(mapping_partitions) > 1:
        utils.unify_triple_files(config)
