"""
Module: memory/graph_store.py

Purpose:
    Provides a clean interface over Neo4j for storing and querying
    the institutional knowledge graph of the memory system.

Responsibilities:
    - Manage Neo4j driver lifecycle (connect, close).
    - Create and upsert graph nodes: Person, Decision, Project, Policy.
    - Create relationships between nodes.
    - Query the graph for people, decisions, projects, and relationships.
    - Provide graph statistics for health checks and audits.
    - Decouple all agents from direct Neo4j dependency.

Workflow:
    Phase 1 — Initialise Neo4j driver on instantiation.
    Phase 2 — Accept node and relationship objects from agents/pipeline.
    Phase 3 — Execute Cypher queries to upsert nodes and relationships.
    Phase 4 — Return structured results to agents.
    Phase 5 — Close driver gracefully on shutdown.
"""

from contextlib import contextmanager
from typing import Any, Generator, Optional

from loguru import logger
from neo4j import GraphDatabase, Driver, Session
from neo4j.exceptions import ServiceUnavailable, AuthError

from config.settings import settings
from schemas.memory_schema import (
    PersonNode,
    DecisionNode,
    ProjectNode,
    PolicyNode,
    GraphRelationship,
    RelationshipType,
    NodeType,
)


class GraphStore:
    """Abstracts all Neo4j graph operations for the Institutional Memory System.

    Provides node creation, relationship management, and graph querying
    as a clean interface consumed by agents and orchestrators.

    Attributes:
        _driver: The Neo4j driver instance managing the connection pool.
    """

    def __init__(self) -> None:
        """Initialises the GraphStore and verifies Neo4j connectivity.

        Raises:
            ServiceUnavailable: If Neo4j is not reachable at the configured URI.
            AuthError: If Neo4j credentials are incorrect.
        """
        logger.info(
            "Connecting to Neo4j | uri='{}'",
            settings.neo4j.uri,
        )

        try:
            self._driver: Driver = GraphDatabase.driver(
                settings.neo4j.uri,
                auth=(settings.neo4j.username, settings.neo4j.password),
            )
            # Verify connectivity immediately on init
            self._driver.verify_connectivity()
            logger.info("Neo4j connection established successfully.")
            self._create_constraints()

        except AuthError as exc:
            logger.error("Neo4j authentication failed: {}", exc)
            raise

        except ServiceUnavailable as exc:
            logger.error(
                "Neo4j unavailable at '{}': {}", settings.neo4j.uri, exc
            )
            raise

    @contextmanager
    def _session(self) -> Generator[Session, None, None]:
        """Provides a managed Neo4j session context.

        Yields:
            An active Neo4j Session instance.

        Raises:
            ServiceUnavailable: If the Neo4j connection is lost.
        """
        session = self._driver.session(database=settings.neo4j.database)
        try:
            yield session
        finally:
            session.close()

    def _create_constraints(self) -> None:
        """Creates uniqueness constraints for all node types in Neo4j.

        Constraints ensure idempotent upserts and improve query performance.
        Safe to call multiple times — Neo4j ignores existing constraints.
        """
        constraints = [
            "CREATE CONSTRAINT person_id IF NOT EXISTS "
            "FOR (p:Person) REQUIRE p.node_id IS UNIQUE",

            "CREATE CONSTRAINT decision_id IF NOT EXISTS "
            "FOR (d:Decision) REQUIRE d.node_id IS UNIQUE",

            "CREATE CONSTRAINT project_id IF NOT EXISTS "
            "FOR (pr:Project) REQUIRE pr.node_id IS UNIQUE",

            "CREATE CONSTRAINT policy_id IF NOT EXISTS "
            "FOR (po:Policy) REQUIRE po.node_id IS UNIQUE",
        ]

        with self._session() as session:
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as exc:
                    # Log but do not raise — constraint may already exist
                    logger.debug("Constraint note: {}", exc)

        logger.info("Neo4j constraints verified.")

    # ── Node Upsert Methods ──────────────────────────────────────────────────

    def upsert_person(self, person: PersonNode) -> None:
        """Creates or updates a Person node in the knowledge graph.

        Uses MERGE to ensure idempotent upserts — safe to call multiple
        times with the same person without creating duplicates.

        Args:
            person: The PersonNode object to upsert.
        """
        cypher = """
            MERGE (p:Person {node_id: $node_id})
            SET p.name       = $name,
                p.email      = $email,
                p.department = $department,
                p.role       = $role,
                p.node_type  = $node_type
        """
        with self._session() as session:
            session.run(
                cypher,
                node_id=person.node_id,
                name=person.name,
                email=person.email,
                department=person.department or "",
                role=person.role or "",
                node_type=person.node_type.value,
            )

        logger.debug("Upserted Person node | email='{}'", person.email)

    def upsert_decision(self, decision: DecisionNode) -> None:
        """Creates or updates a Decision node in the knowledge graph.

        Args:
            decision: The DecisionNode object to upsert.
        """
        cypher = """
            MERGE (d:Decision {node_id: $node_id})
            SET d.summary          = $summary,
                d.date             = $date,
                d.source_message_id = $source_message_id,
                d.department       = $department,
                d.node_type        = $node_type
        """
        with self._session() as session:
            session.run(
                cypher,
                node_id=decision.node_id,
                summary=decision.summary,
                date=decision.date.isoformat() if decision.date else "",
                source_message_id=decision.source_message_id,
                department=decision.department or "",
                node_type=decision.node_type.value,
            )

        logger.debug(
            "Upserted Decision node | id='{}'", decision.node_id
        )

    def upsert_project(self, project: ProjectNode) -> None:
        """Creates or updates a Project node in the knowledge graph.

        Args:
            project: The ProjectNode object to upsert.
        """
        cypher = """
            MERGE (pr:Project {node_id: $node_id})
            SET pr.name       = $name,
                pr.status     = $status,
                pr.start_date = $start_date,
                pr.end_date   = $end_date,
                pr.node_type  = $node_type
        """
        with self._session() as session:
            session.run(
                cypher,
                node_id=project.node_id,
                name=project.name,
                status=project.status or "",
                start_date=project.start_date.isoformat() if project.start_date else "",
                end_date=project.end_date.isoformat() if project.end_date else "",
                node_type=project.node_type.value,
            )

        logger.debug(
            "Upserted Project node | name='{}'", project.name
        )

    def upsert_policy(self, policy: PolicyNode) -> None:
        """Creates or updates a Policy node in the knowledge graph.

        Args:
            policy: The PolicyNode object to upsert.
        """
        cypher = """
            MERGE (po:Policy {node_id: $node_id})
            SET po.title          = $title,
                po.content        = $content,
                po.effective_date = $effective_date,
                po.last_updated   = $last_updated,
                po.node_type      = $node_type
        """
        with self._session() as session:
            session.run(
                cypher,
                node_id=policy.node_id,
                title=policy.title,
                content=policy.content,
                effective_date=policy.effective_date.isoformat() if policy.effective_date else "",
                last_updated=policy.last_updated.isoformat() if policy.last_updated else "",
                node_type=policy.node_type.value,
            )

        logger.debug(
            "Upserted Policy node | title='{}'", policy.title
        )

    # ── Relationship Methods ─────────────────────────────────────────────────

    def create_relationship(self, relationship: GraphRelationship) -> None:
        """Creates a directed relationship between two existing nodes.

        Uses MERGE to avoid duplicate relationships between the same
        pair of nodes with the same relationship type.

        Args:
            relationship: The GraphRelationship object defining the edge.
        """
        # Dynamically build the relationship type into the Cypher string.
        # Neo4j does not support parameterised relationship types.
        cypher = f"""
            MATCH (a {{node_id: $from_id}})
            MATCH (b {{node_id: $to_id}})
            MERGE (a)-[r:{relationship.relationship_type.value}]->(b)
            SET r += $properties
        """
        with self._session() as session:
            session.run(
                cypher,
                from_id=relationship.from_node_id,
                to_id=relationship.to_node_id,
                properties=relationship.properties,
            )

        logger.debug(
            "Created relationship | {}→[{}]→{}",
            relationship.from_node_id,
            relationship.relationship_type.value,
            relationship.to_node_id,
        )

    # ── Query Methods ────────────────────────────────────────────────────────

    def get_person_by_email(self, email: str) -> Optional[dict]:
        """Retrieves a Person node by email address.

        Args:
            email: The email address to search for.

        Returns:
            A dictionary of node properties, or None if not found.
        """
        cypher = """
            MATCH (p:Person {email: $email})
            RETURN p
        """
        with self._session() as session:
            result = session.run(cypher, email=email.lower())
            record = result.single()
            return dict(record["p"]) if record else None

    def get_decisions_by_person(self, email: str) -> list[dict]:
        """Retrieves all Decision nodes linked to a specific person.

        Args:
            email: The email address of the person.

        Returns:
            List of decision property dictionaries.
        """
        cypher = """
            MATCH (p:Person {email: $email})-[:MADE_DECISION]->(d:Decision)
            RETURN d
            ORDER BY d.date DESC
        """
        with self._session() as session:
            result = session.run(cypher, email=email.lower())
            return [dict(record["d"]) for record in result]

    def get_decisions_by_department(self, department: str) -> list[dict]:
        """Retrieves all Decision nodes associated with a department.

        Args:
            department: The department name to filter by.

        Returns:
            List of decision property dictionaries.
        """
        cypher = """
            MATCH (d:Decision {department: $department})
            RETURN d
            ORDER BY d.date DESC
        """
        with self._session() as session:
            result = session.run(cypher, department=department)
            return [dict(record["d"]) for record in result]

    def get_people_in_department(self, department: str) -> list[dict]:
        """Retrieves all Person nodes belonging to a department.

        Args:
            department: The department name to filter by.

        Returns:
            List of person property dictionaries.
        """
        cypher = """
            MATCH (p:Person {department: $department})
            RETURN p
            ORDER BY p.name
        """
        with self._session() as session:
            result = session.run(cypher, department=department)
            return [dict(record["p"]) for record in result]

    def get_projects_for_person(self, email: str) -> list[dict]:
        """Retrieves all Project nodes linked to a specific person.

        Args:
            email: The email address of the person.

        Returns:
            List of project property dictionaries.
        """
        cypher = """
            MATCH (p:Person {email: $email})-[:INVOLVED_IN]->(pr:Project)
            RETURN pr
        """
        with self._session() as session:
            result = session.run(cypher, email=email.lower())
            return [dict(record["pr"]) for record in result]

    def get_communication_network(self, email: str) -> list[dict]:
        """Retrieves all people a person has communicated with.

        Args:
            email: The email address of the central person.

        Returns:
            List of connected person property dictionaries.
        """
        cypher = """
            MATCH (p:Person {email: $email})-[:COMMUNICATED_WITH]->(other:Person)
            RETURN other
            ORDER BY other.name
        """
        with self._session() as session:
            result = session.run(cypher, email=email.lower())
            return [dict(record["other"]) for record in result]

    def search_decisions(self, keyword: str) -> list[dict]:
        """Full-text search over Decision node summaries.

        Args:
            keyword: Keyword to search for in decision summaries.

        Returns:
            List of matching decision property dictionaries.
        """
        cypher = """
            MATCH (d:Decision)
            WHERE toLower(d.summary) CONTAINS toLower($keyword)
            RETURN d
            ORDER BY d.date DESC
        """
        with self._session() as session:
            result = session.run(cypher, keyword=keyword)
            return [dict(record["d"]) for record in result]

    # ── Statistics & Health ──────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Returns node and relationship counts for health checks.

        Returns:
            Dictionary with counts for each node type and relationships.
        """
        cypher = """
            MATCH (n)
            RETURN labels(n)[0] AS label, count(n) AS count
        """
        rel_cypher = """
            MATCH ()-[r]->()
            RETURN count(r) AS total_relationships
        """
        stats: dict[str, Any] = {}

        with self._session() as session:
            for record in session.run(cypher):
                stats[record["label"]] = record["count"]

            rel_result = session.run(rel_cypher).single()
            stats["total_relationships"] = (
                rel_result["total_relationships"] if rel_result else 0
            )

        return stats

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Closes the Neo4j driver and releases all connections.

        Should be called on application shutdown.
        """
        self._driver.close()
        logger.info("Neo4j driver closed.")