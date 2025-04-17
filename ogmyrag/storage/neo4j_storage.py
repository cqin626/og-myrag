import logging
from neo4j import GraphDatabase

neo4j_logger = logging.getLogger("neo4j")

class Neo4jStorage:
    def __init__(self, uri: str, user: str, password: str):
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            self.driver.verify_connectivity()
            neo4j_logger.info("Connected to Neo4j successfully.")
        except Exception as e:
            neo4j_logger.error(f"Failed to connect to Neo4j: {e}")
            raise

    def close(self):
        try:
            self.driver.close()
            neo4j_logger.info("Neo4j connection closed.")
        except Exception as e:
            neo4j_logger.error(f"Error closing connection: {e}")

    def insert_entities(self, entities: list[dict], label: str):
        """Insert a list of entities from JSON to the graph."""
        try:
            with self.driver.session() as session:
                for entity in entities:
                    query = f"CREATE (n:{label} $props)"
                    session.run(query, props=entity)
                
                neo4j_logger.info(f"Successfully inserted {len(entities)} entity(ies) with label {label}")
        except Exception as e:
            neo4j_logger.error(f"Failed to insert entities: {str(e)}")
            raise

    def insert_relationships(self, relationships: list[dict]):
        """Insert a list of relationships from JSON to the graph."""
        try:
            with self.driver.session() as session:
                for rel in relationships:
                    source_id = rel.get('source_id')
                    target_id = rel.get('target_id')
                    rel_type = rel.get('type')
                    properties = rel.get('properties', {})

                    if not all([source_id, target_id, rel_type]):
                        neo4j_logger.warning(f"Skipping invalid relationship: {rel}")
                        continue

                    query = (
                        f"MATCH (a), (b) "
                        f"WHERE a.id = $source_id AND b.id = $target_id "
                        f"CREATE (a)-[r:{rel_type} $props]->(b)"
                    )
                    session.run(query, source_id=source_id, target_id=target_id, props=properties)
                
                neo4j_logger.info(f"Successfully inserted {len(relationships)} relationship(s)")
        except Exception as e:
            neo4j_logger.error(f"Failed to insert relationships: {str(e)}")
            raise

    def update_node(self, node_id: str, properties: dict):
        """Update a particular node with new properties."""
        try:
            with self.driver.session() as session:
                query = (
                    "MATCH (n) WHERE n.id = $node_id "
                    "SET n += $props "
                    "RETURN n"
                )
                result = session.run(query, node_id=node_id, props=properties)
                
                if result.peek() is None:
                    neo4j_logger.warning(f"No node found with id {node_id}")
                    return
                
                neo4j_logger.info(f"Successfully updated node with id {node_id}")
        except Exception as e:
            neo4j_logger.error(f"Failed to update node {node_id}: {str(e)}")
            raise

    def delete_node(self, node_id: str):
        """Delete a particular node."""
        try:
            with self.driver.session() as session:
                # First detach relationships
                query_detach = (
                    "MATCH (n) WHERE n.id = $node_id "
                    "DETACH DELETE n"
                )
                result = session.run(query_detach, node_id=node_id)
                
                summary = result.consume()
                if summary.counters.nodes_deleted == 0:
                    neo4j_logger.warning(f"No node found with id {node_id}")
                    return
                
                neo4j_logger.info(f"Successfully deleted node with id {node_id}")
        except Exception as e:
            neo4j_logger.error(f"Failed to delete node {node_id}: {str(e)}")
            raise

    def run_query(self, query, parameters=None):
        """Run any custom Cypher query."""
        try:
            with self.driver.session() as session:
                result = session.run(query, parameters or {})
                return [record.data() for record in result]
        except Exception as e:
            neo4j_logger.error(f"Failed to run custom query: {e}")
            return []
