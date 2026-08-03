<?xml version="1.0" encoding="UTF-8"?>
<!--
  order.xsl — Transform inbound JSON order (converted to XML by preceding step)
  to S/4HANA SOAP/XML format.

  Spec ref: §26.3 reference scenario.
  This XSLT 1.0 stylesheet works with the Python prototype (lxml).
  Phase 2 will support XSLT 2.0 subset via Saxon-HE.
-->
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="xml" indent="yes"/>

  <xsl:template match="/">
    <S4Order>
      <xsl:apply-templates select="*"/>
    </S4Order>
  </xsl:template>

  <xsl:template match="*">
    <xsl:element name="{local-name()}">
      <xsl:apply-templates select="@*|node()"/>
    </xsl:element>
  </xsl:template>

  <xsl:template match="@*|text()">
    <xsl:copy/>
  </xsl:template>
</xsl:stylesheet>
