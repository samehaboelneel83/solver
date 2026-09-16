from app.graph.schemas import (
    AttributeDefinitionOption,
    EntityTypeOption,
    GraphEdge,
    GraphNode,
    GraphResponse,
    HierarchyOption,
    RelationshipTypeOption,
)


def test_graph_node_defaults():
    node = GraphNode(id="e1", type="Employee", label="Ahmed")
    assert node.parent is None
    assert node.attributes == {}


def test_graph_node_with_parent_and_attributes():
    node = GraphNode(id="e1", type="Employee", label="Ahmed", parent="u1", attributes={"rank": "Captain"})
    assert node.parent == "u1"
    assert node.attributes == {"rank": "Captain"}


def test_graph_edge_defaults():
    edge = GraphEdge(id="r1", source="e1", target="u1", type="works_for", label="Works For")
    assert edge.attributes == {}


def test_graph_response_round_trip():
    response = GraphResponse(
        nodes=[GraphNode(id="e1", type="Employee", label="Ahmed")],
        edges=[GraphEdge(id="r1", source="e1", target="u1", type="works_for", label="Works For")],
        entity_types=[EntityTypeOption(id="t1", code="employee", name="Employee", is_abstract=False)],
        relationship_types=[
            RelationshipTypeOption(
                id="rt1", code="works_for", name="Works For", is_directed=True,
                source_entity_type="employee", target_entity_type="unit",
            )
        ],
        hierarchies=[HierarchyOption(id="h1", code="org-chart", name="Org Chart")],
        attribute_definitions=[
            AttributeDefinitionOption(id="a1", entity_type_id="t1", code="rank", name="Rank", data_type="string")
        ],
    )
    dumped = response.model_dump()
    assert dumped["nodes"][0]["id"] == "e1"
    restored = GraphResponse.model_validate(dumped)
    assert restored.edges[0].source == "e1"
