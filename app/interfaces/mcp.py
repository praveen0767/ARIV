# Phase 1: Empty interface declarations for MCPToolRegistry and ToolRiskClassification
import enum

class ToolRiskClassification(enum.Enum):
    READ = "READ"
    WRITE = "WRITE"
    FINANCIAL = "FINANCIAL"
    COMMUNICATION = "COMMUNICATION"

class MCPToolRegistry:
    pass
