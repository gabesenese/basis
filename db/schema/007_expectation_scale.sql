/*
  An expectation was a rate when this column was written, and a rate in basis
  points fits in ten digits with room to spare. A company's revenue does not:
  NVIDIA's quarter is around forty six billion dollars, which overflows the
  precision on the first row it is asked to hold.

  Widening rather than rescaling. Storing revenue in millions would put the
  unit in a comment and nowhere the database could enforce it, and the next
  reader would have no way to tell a number in millions from a number in
  dollars except by knowing which measure it came from. The column holds what
  the measure is denominated in, and the measure says what that is.
*/

alter table basis.expectation
  alter column point_value type numeric(28,8);
