import logging
from collections import defaultdict
from neo4j import AsyncGraphDatabase

neo4j_logger = logging.getLogger("neo4j")


class AsyncNeo4jStorage:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def connect(self):
        try:
            await self.driver.verify_connectivity()
            neo4j_logger.info("Connected to Neo4j successfully.")
        except Exception as e:
            neo4j_logger.error(f"Failed to connect to Neo4j: {e}")
            raise

    async def close(self):
        try:
            await self.driver.close()
            neo4j_logger.info("Neo4j connection closed.")
        except Exception as e:
            neo4j_logger.error(f"Error closing connection: {e}")

    async def upsert_entities(self, entities: list[dict]):
        """
        Upserts a list of entities with potentially mixed labels into Neo4j.

        Args:
            entities (list[dict]): A list of entity dictionaries. Each dictionary MUST contain a 'type' key for the node label and a unique 'id' key for merging.
        """
        if not entities:
            return

        # Step 1: Group entities by their label ('type' field) internally.
        entities_by_label = defaultdict(list)
        for entity in entities:
            label = entity.get("type")
            entity_id = entity.get("id")

            if not all([label, entity_id]):
                neo4j_logger.warning(
                    f"Skipping entity with missing 'type' or 'id': {entity}"
                )
                continue
            entities_by_label[label].append(entity)

        # Step 2: Execute one batch upsert query for each label.
        try:
            async with self.driver.session() as session:
                for label, entity_list in entities_by_label.items():
                    # MERGE finds a node with the given label and id.
                    # ON CREATE runs if the node is new.
                    # ON MATCH runs if the node already exists.
                    query = f"""
                    UNWIND $entities AS props
                    MERGE (n:{label} {{id: props.id}})
                    ON CREATE SET n = props
                    ON MATCH SET n += props
                    """
                    await session.run(query, entities=entity_list)

            neo4j_logger.info(
                f"Successfully upserted {len(entities)} entity(ies) "
                f"across {len(entities_by_label)} labels in Neo4j."
            )
        except Exception as e:
            neo4j_logger.error(f"Failed to batch upsert entities: {str(e)}")
            raise

    async def upsert_relationships(self, relationships: list[dict]):
        if not relationships:
            return

        # Step 1: Group relationships by their type
        rels_by_type = defaultdict(list)
        for rel in relationships:
            source_id = rel.get("source_id")
            target_id = rel.get("target_id")
            rel_type = rel.get("type")
            rel_id = rel.get("properties", {}).get("id")

            if not all([source_id, target_id, rel_type, rel_id]):
                neo4j_logger.warning(
                    f"Skipping invalid relationship with missing fields: {rel}"
                )
                continue

            rels_by_type[rel_type].append(rel)

        # Step 2: Execute one batch upsert query for each relationship type.
        try:
            async with self.driver.session() as session:
                for rel_type, rel_list in rels_by_type.items():
                    query = f"""
                        UNWIND $rels AS rel
                        MERGE (a {{id: rel.source_id}})
                        MERGE (b {{id: rel.target_id}})
                        MERGE (a)-[r:`{rel_type}` {{id: rel.properties.id}}]->(b)
                        ON CREATE SET r = rel.properties
                        ON MATCH SET r += rel.properties
                    """
                    await session.run(query, rels=rel_list)

            neo4j_logger.info(
                f"Successfully upserted {len(relationships)} relationship(s) across {len(rels_by_type)} types."
            )
        except Exception as e:
            neo4j_logger.error(f"Failed to batch upsert relationships: {str(e)}")
            raise

    async def update_node(self, node_id: str, properties: dict):
        try:
            async with self.driver.session() as session:
                query = "MATCH (n) WHERE n.id = $node_id " "SET n += $props " "RETURN n"
                result = await session.run(query, node_id=node_id, props=properties)
                record = await result.single()

                if not record:
                    neo4j_logger.warning(f"No node found with id {node_id}")
                else:
                    neo4j_logger.info(f"Successfully updated node with id {node_id}")
        except Exception as e:
            neo4j_logger.error(f"Failed to update node {node_id}: {str(e)}")
            raise

    async def delete_node(self, node_id: str):
        try:
            async with self.driver.session() as session:
                query_detach = "MATCH (n) WHERE n.id = $node_id " "DETACH DELETE n"
                result = await session.run(query_detach, node_id=node_id)
                summary = await result.consume()

                if summary.counters.nodes_deleted == 0:
                    neo4j_logger.warning(f"No node found with id {node_id}")
                else:
                    neo4j_logger.info(f"Successfully deleted node with id {node_id}")
        except Exception as e:
            neo4j_logger.error(f"Failed to delete node {node_id}: {str(e)}")
            raise

    async def run_query(self, query: str, parameters=None):
        try:
            async with self.driver.session() as session:
                result = await session.run(query, parameters or {})
                records = []
                async for record in result:
                    records.append(record.data())
                return records
        except Exception as e:
            neo4j_logger.error(f"Failed to run custom query: {e}")
            return []
